// 中国彩票分析工具 — Tauri 壳
//
// 职责:
//   1. 启动 Python sidecar (Flask 后端)
//   2. 等待端口就绪 (最多 30 秒)
//   3. 把主窗口导航到 http://127.0.0.1:<port>
//   4. 窗口关闭时终止 sidecar, 不留孤儿进程
//
// 设计要点:
//   - 端口用 0 让系统分配, 避免和已有服务冲突
//   - sidecar 进程用 kill_on_drop, 父进程退出时一并清理
//   - 启动失败要在窗口里给出可读提示, 而不是白屏

use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, WindowEvent};

/// 全局持有 sidecar 句柄, 退出时 kill
static SIDECAR: Mutex<Option<Child>> = Mutex::new(None);

/// 选一个空闲端口 (让 OS 分配, 避免冲突)
fn pick_port() -> u16 {
    // 绑定 0 端口, 拿到系统分配的实际端口后立刻释放
    let l = std::net::TcpListener::bind("127.0.0.1:0").expect("bind ephemeral");
    let port = l.local_addr().map(|a| a.port()).unwrap_or(9876);
    drop(l);
    port
}

/// 简单 URL 编码 (用于 data URL)
fn urlencode(s: &str) -> String {
    let mut out = String::with_capacity(s.len() * 3);
    for b in s.as_bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(*b as char)
            }
            _ => out.push_str(&format!("%{:02X}", b)),
        }
    }
    out
}

/// 检查端口是否已经在监听
fn port_ready(port: u16) -> bool {
    TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}").parse().expect("addr"),
        Duration::from_millis(300),
    )
    .is_ok()
}

/// 定位 Python 解释器
///
/// 优先级:
///   1. 环境变量 LOTTERY_PYTHON (打包发行时指向内嵌解释器)
///   2. 资源目录下的 sidecar/python.exe (打包版)
///   3. 系统 PATH 里的 python
fn find_python(app: &tauri::AppHandle) -> Option<String> {
    if let Ok(p) = std::env::var("LOTTERY_PYTHON") {
        if Path::new(&p).exists() {
            return Some(p);
        }
    }
    // 打包版: 资源目录
    if let Ok(res) = app.path().resource_dir() {
        let cand = res.join("sidecar").join("python.exe");
        if cand.exists() {
            return Some(cand.to_string_lossy().into_owned());
        }
    }
    // 开发版: 项目里的 venv
    if let Ok(res) = app.path().resource_dir() {
        // 打包时 python.exe 和 scripts/ 在同一层
        let cand = res.join("python.exe");
        if cand.exists() {
            return Some(cand.to_string_lossy().into_owned());
        }
    }
    // 系统 python
    for name in ["python", "python3", "py"] {
        let out = Command::new(name)
            .arg("--version")
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .output();
        if let Ok(o) = out {
            if o.status.success() {
                return Some(name.to_string());
            }
        }
    }
    None
}

/// 定位项目根目录 (含 scripts/pick_gui.py 的那一层)
///
/// 优先级:
///   1. 环境变量 LOTTERY_PROJECT_ROOT (显式指定, 最可靠)
///   2. 打包版: 资源目录 / 资源目录的上一级
///   3. 开发版: 从 exe 往上找
///   4. 当前工作目录往上找
fn find_project_root(app: &tauri::AppHandle) -> Option<PathBuf> {
    // 1. 显式指定
    if let Ok(p) = std::env::var("LOTTERY_PROJECT_ROOT") {
        let pb = PathBuf::from(&p);
        if pb.join("scripts").join("pick_gui.py").exists() {
            return Some(pb);
        }
    }
    // 2. 打包版
    if let Ok(res) = app.path().resource_dir() {
        let mut cands: Vec<PathBuf> = vec![res.clone()];
        if let Some(p) = res.parent() {
            cands.push(p.to_path_buf());
        }
        for c in cands {
            if c.join("scripts").join("pick_gui.py").exists() {
                return Some(c);
            }
        }
    }
    // 3. 从 exe 往上找
    if let Ok(exe) = std::env::current_exe() {
        let mut dir: Option<PathBuf> = exe.parent().map(|p| p.to_path_buf());
        for _ in 0..8 {
            match dir.clone() {
                Some(d) => {
                    if d.join("scripts").join("pick_gui.py").exists() {
                        return Some(d);
                    }
                    dir = d.parent().map(|p| p.to_path_buf());
                }
                None => break,
            }
        }
    }
    // 4. 当前工作目录往上找
    if let Ok(cwd) = std::env::current_dir() {
        let mut dir: Option<PathBuf> = Some(cwd);
        for _ in 0..8 {
            match dir.clone() {
                Some(d) => {
                    if d.join("scripts").join("pick_gui.py").exists() {
                        return Some(d);
                    }
                    dir = d.parent().map(|p| p.to_path_buf());
                }
                None => break,
            }
        }
    }
    None
}

/// 启动后端, 返回端口
fn start_backend(app: &tauri::AppHandle) -> Result<u16, String> {
    let python = find_python(app).ok_or(
        "找不到 Python 解释器. 请安装 Python 3.10+ 或设置 LOTTERY_PYTHON 环境变量",
    )?;
    let root = find_project_root(app).ok_or(
        "找不到项目目录 (scripts/pick_gui.py). 请确认安装完整",
    )?;
    let port = pick_port();

    let script = root.join("scripts").join("pick_gui.py");
    eprintln!("[sidecar] python={} root={} port={}", python, root.display(), port);

    let child = Command::new(&python)
        .arg(&script)
        .arg("--port")
        .arg(port.to_string())
        .current_dir(&root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("启动 Python 失败: {e}"))?;

    // 等待端口就绪 (最多 40 秒)
    let deadline = Instant::now() + Duration::from_secs(40);
    while Instant::now() < deadline {
        if port_ready(port) {
            let mut guard = SIDECAR.lock().unwrap();
            *guard = Some(child);
            return Ok(port);
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    Err("后端启动超时 (40 秒). 检查 Python 环境和依赖是否完整".to_string())
}

#[tauri::command]
fn backend_info(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let port = start_backend(&app)?;
    Ok(serde_json::json!({ "port": port, "url": format!("http://127.0.0.1:{port}/") }))
}

#[tauri::command]
fn shutdown_backend() {
    let mut guard = SIDECAR.lock().unwrap();
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![backend_info, shutdown_backend])
        .setup(|app| {
            // 启动后端并导航
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                match start_backend(&handle) {
                    Ok(port) => {
                        let url = format!("http://127.0.0.1:{port}/");
                        eprintln!("[tauri] backend ready: {url}");
                        if let Some(w) = handle.get_webview_window("main") {
                            if let Ok(u) = tauri::Url::parse(&url) {
                                let _ = w.navigate(u);
                            }
                        }
                    }
                    Err(e) => {
                        eprintln!("[tauri] backend start failed: {e}");
                        // 用 data URL 承载错误页 (纯 HTML 字符串没有 base URL 会 panic)
                        let html = format!(
                            "<!doctype html><meta charset=\"utf-8\">\
<body style=\"font-family:system-ui;background:#0f172a;color:#e2e8f0;padding:40px\">\
<h2>后端启动失败</h2><pre style=\"color:#f87171\">{e}</pre>\
<p style=\"color:#94a3b8\">请确认已安装 Python 3.10+ 并安装依赖:<br>\
<code>pip install -r requirements-ci.txt</code></p>\
<p style=\"color:#94a3b8\">如项目不在默认位置, 请设置环境变量 \
<code>LOTTERY_PROJECT_ROOT</code> 指向项目根目录.</p></body>"
                        );
                        let url = tauri::Url::parse(&format!(
                            "data:text/html;charset=utf-8,{}",
                            urlencode(&html)
                        )).ok();
                        if let (Some(u), Some(w)) = (url, handle.get_webview_window("main")) {
                            let _ = w.navigate(u);
                        }
                    }
                }
            });
            Ok(())
        })
        .on_window_event(|_window, event| {
            if let WindowEvent::Destroyed = event {
                shutdown_backend();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
