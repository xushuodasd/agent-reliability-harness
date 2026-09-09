# Artifact integrity and completeness / 证据清单校验

`verify_manifest(path)` validates the packaged manifest schema, rejects empty or
malformed artifact lists, duplicate/canonical-path violations, missing or unreadable
files, and mismatching sizes or SHA-256 values. It does not write or repair files.

Basic verification checks only what the manifest declares. An omitted declaration
cannot be detected from that declaration list alone. Callers that know the expected
evidence boundary must supply it independently:

```python
from pathlib import Path
from pilot_harness.manifests import verify_manifest

valid, errors = verify_manifest(
    Path("run/manifest.json"),
    required_artifacts=["plan.json", "summary.json"],
)
```

Required paths must be canonical relative POSIX paths, not a single string.
Required-file checking permits additional declared artifacts; it does not assert
that there are no unlisted files on disk. Paths using traversal, absolute paths,
backslashes, drive/stream colons, redundant separators or self-reference are rejected.
Resolved paths must remain within the run directory. This is a quiescent-directory
check, not protection against concurrent file-system changes or a hostile host.

The [dispatch diagnostic](dispatch-diagnostic.md) now derives its 98 required paths
from the fixed 48-cell design rather than trusting a possibly edited manifest.
Other callers retain declared-file verification unless they supply their own required
boundary. In particular, this change does not by itself add omission detection to
all historical unified-engine runs.

## 中文边界说明

本轮修复“空清单可能通过”和错误结构导致异常的问题，并提供独立的必需文件检查。
清单漏掉一个文件时，如果调用方没有独立给出必需集合，基础校验仍无法知道它缺失。
新的诊断输出已使用这个完整性接口，旧运行文件不回填、不重写。

不要混淆三种不同判断：

- 字节完整性：现有文件是否与清单记录匹配。
- 必需文件覆盖：指定的证据是否全部列出且可读取。
- 科学有效性：计划是否公平、数据是否真实、评分与分析是否正确。

本工具只检查前两项中被明确配置的部分。未签名的清单不是不可篡改保证，也不能
证明实验发生时间或真人审查。科学有效性和统一引擎语义联接仍需单独验收。
