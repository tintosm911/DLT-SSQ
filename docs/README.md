# 文档索引

本项目的**设计与理论文档**。README 是入口，这里是深入材料。

---

## 核心文档

| 文档 | 内容 | 什么时候看 |
|---|---|---|
| [dan_tuo_theory.md](dan_tuo_theory.md) | **胆拖结构理论** —— 为什么"追热号"在概率上毫无意义（完整超几何推导 + 定理 + 实证） | 想理解胆拖/选号策略到底有没有用时 |
| [prize_rules_spec.md](prize_rules_spec.md) | **奖级规则规范** —— 唯一真相源、浮动奖口径、改动流程 | 要改奖级规则、或核对期望值数字时 |
| [data_audit.md](data_audit.md) | **数据完整性审计报告** —— 两个库的期数/连续性/断层归因 | 怀疑数据有问题、或质疑某个统计结论时 |

---

## 三份文档的共同立场

这个项目的核心立场是**诚实**：

1. **期望值不可改** —— 任何选号策略、任何公式、任何"AI 模型"都改不了号码彩的负期望
2. **口径要统一** —— 同一个数字在不同地方必须一致（v2.5.0 修的就是这个）
3. **数据要审计** —— 结论建立在自己的数据上，而不是推测上
4. **交叉验证** —— 关键结论要有两套独立实现互证

---

## 相关代码入口

| 主题 | 文件 |
|---|---|
| 判奖（权威） | `data/pick_advisor.py::judge_prize` |
| 奖级表（镜像） | `data/games.py::PRIZE_RULES` |
| 奖级一致性守门 | `scripts/check_prize_consistency.py` |
| 胆拖精确求解器 | `data/dan_tuo_exact.py` |
| 胆拖独立交叉验证 | `scripts/verify_dan_tuo_exact.py` |
| 数据完整性审计 | `scripts/audit_data_integrity.py` |
| 胆拖分析入口 | `scripts/analyze_dantuo.py` / `compare_dantuo_schemes.py` / `dantuo_structure_matrix.py` / `dantuo_final_compare.py` |

---

## 文档维护约定

- **规范类**文档（`prize_rules_spec.md`）：改代码就要改文档，一次提交里完成
- **理论类**文档（`dan_tuo_theory.md`）：推导变化时更新；实证部分必须附**可复现命令**
- **报告类**文档（`data_audit.md`）：数据变化后重跑审计脚本并更新结论
