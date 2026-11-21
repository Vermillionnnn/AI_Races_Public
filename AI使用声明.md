# AI 使用声明

这个仓库里的绝大部分内容是 AI 写的，作者没有逐行审过。使用前请先读完这一页。

## 哪些是 AI 写的

- **选手提交**（`submissions/` 下的代码、README、worklog）：全部由参赛的 AI 模型在比赛时限内独立完成。代码没有修改，只在判分时运行过；README 和 worklog 除去了和隐私、环境有关的敏感信息。
- **选手包、裁判程序、参考程序、成绩和说明文档**：在作者的指导下由 AI 编程助手编写和整理，作者审阅过规则和结论，但没有逐行审过代码。
- 作者自己定的是：比赛规则、计分方法、判分时的取舍和最终成绩。

## 运行代码请注意安全

- **不保证正确，也不保证安全。** 代码按原样提供，不附任何担保。选手代码只在比赛规定的输入上测过，在别的输入上可能出错、卡死或占满内存。
- **建议在隔离环境里运行**：虚拟机、容器或一次性的云电脑，不要在存有重要数据或登录了个人账号的机器上直接跑。
- **先读再跑。** 尤其是选手提交的程序和脚本，运行前看一眼它会读写哪些文件、会不会启动别的进程。
- 编译选项、运行方式以各目录的 README 为准。

## 成绩和评述

成绩表里的数字是在作者的判分环境里实测的，换一台机器会有差别。README 和 `results.md` 里对选手做法的分析部分出自 AI 助手的阅读，作者核对过主要结论，但细节可能有误；发现错误欢迎开 Issue。

---

# AI Usage Notice

Most of this repository was written by AI and has **not** been reviewed line by line.

- **Submissions** (`submissions/`) were written entirely by the competing AI models within the time limit. Code is published unmodified; READMEs and work logs had privacy- and environment-related details removed.
- **Player kits, judges, reference programs, results and docs** were written by AI coding assistants under the author's direction. The author defined the rules, scoring and final results, but did not review all code line by line.
- **No warranty.** Code is provided as is. Run it in an isolated environment (VM, container or disposable machine), and read it before running.
- Timings were measured on the author's judging machine and will differ elsewhere. Analyses of contestants' approaches were drafted by AI and may contain errors; issues are welcome.
