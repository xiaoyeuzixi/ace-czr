# ACE/CZR 逆向分析资料与 NoACE 一键启动程序

[![GitHub](https://img.shields.io/badge/GitHub-xiaoyeuzixi%2Face--czr-blue)](https://github.com/xiaoyeuzixi/ace-czr)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Language](https://img.shields.io/badge/Language-C%23-purple)]()

## 项目简介

ACE_CZR 逆向分析资料与 NoACE 一键启动程序，包含完整的逆向分析文档、源码和工具。

## 仓库信息

| 项目 | 值 |
|------|-----|
| 仓库地址 | https://github.com/xiaoyeuzixi/ace-czr |
| 可见性 | PUBLIC (开源) |
| 主要语言 | C# |
| 默认分支 | main |

## 目录结构

```
ace-czr/
├── 03_ACE处理源码与分析/      # ACE 逆向分析源码和文档
├── 04_NoACE一键启动程序/      # NoACE 一键启动工具
├── CLEANUP_REPORT.md          # 清理报告
├── FILE_MANIFEST.csv          # 文件清单
├── README_总览.md             # 总览文档
├── SHA256SUMS.txt             # SHA256 校验和
└── 仓库更新报告.md            # 仓库更新报告
```

## 使用说明

### 启动游戏

```powershell
# 双击运行
04_NoACE一键启动程序\Start_NoACE.cmd
```

### 编译源码

使用 Visual Studio 2022 打开解决方案文件，选择 `Release | x64` 配置编译。

## 文件校验

- `SHA256SUMS.txt` - 交付文件的 SHA-256 校验和
- `FILE_MANIFEST.csv` - 文件清单（相对路径、大小、分类）
- `CLEANUP_REPORT.md` - 清理前后体积及删除类别

## 更新日志

### v1.0.0 (2026-08-18)
- 首次开源发布
- 添加仓库更新报告

## 许可证

本项目采用 [MIT 许可证](LICENSE)。

## 联系方式

- GitHub: [@xiaoyeuzixi](https://github.com/xiaoyeuzixi)

---

**注意**: 本项目仅供学习和研究使用，请勿用于非法用途。
