# SCE operation 3e9f89ad-916a-4f01-8b41-85cdfc0ea96e

Outcome: **succeeded**

Verification: **passed**

```json
{
  "capability_id": "python.build",
  "id": "3e9f89ad-916a-4f01-8b41-85cdfc0ea96e",
  "task_id": null,
  "requested": {
    "operation": "BUILD_ORIGINAL_PROJECT",
    "source": "I:\\SPIDER-CREATOR-ENGINE\\examples\\fixtures\\success",
    "trusted": true
  },
  "planned": {
    "source": "I:\\SPIDER-CREATOR-ENGINE\\examples\\fixtures\\success",
    "output_root": "I:\\SPIDER-CREATOR-ENGINE\\.sce\\acceptance\\foundation-v0.1\\build-output",
    "operation": "BUILD_ORIGINAL_PROJECT",
    "trusted": true,
    "task_id": null,
    "artifact_name": "hello-sce.pyz",
    "entry_point": "main:main",
    "required_modules": [],
    "verification_args": [
      "Ada"
    ],
    "expected_stdout": "Hello, Ada. Human time matters.\n",
    "expected_exit": 0,
    "files": [
      {
        "path": "main.py",
        "sha256": "ab70878bd589f28b493b3cc39b01af352d8411c217512fc543515f4c0d4c2b1a",
        "size": 192
      },
      {
        "path": "sce-build.json",
        "sha256": "62b97d13d7235f55ed83b7f34d28428e01868be9f7f8b643ec08d1d27aebd796",
        "size": 240
      }
    ],
    "validation_errors": [],
    "unsupported": false
  },
  "outcome": "succeeded",
  "verification": "passed",
  "executed": [
    {
      "stage": "execute",
      "operation": "zipapp.create_archive",
      "entry_point": "main:main"
    },
    {
      "stage": "verify",
      "status": "passed",
      "argv": [
        "I:\\SPIDER-CREATOR-ENGINE\\.sce\\acceptance\\foundation-v0.1\\installed\\Scripts\\python.exe",
        "-I",
        "I:\\SPIDER-CREATOR-ENGINE\\.sce\\acceptance\\foundation-v0.1\\build-output\\hello-sce.pyz",
        "Ada"
      ],
      "expected_stdout": "Hello, Ada. Human time matters.\n",
      "expected_exit": 0,
      "stdout": "Hello, Ada. Human time matters.\n",
      "stderr": "",
      "exit_code": 0,
      "detail": "declared exit and stdout matched",
      "elapsed_seconds": 0.07006630000068981
    }
  ],
  "produced": [
    {
      "kind": "python_zipapp",
      "path": "I:\\SPIDER-CREATOR-ENGINE\\.sce\\acceptance\\foundation-v0.1\\build-output\\hello-sce.pyz",
      "sha256": "f325aee2eb9d7e196bff2fb41d6a2c59356403070b8e04bb3d1b2af4495ecbc8",
      "size": 671
    }
  ],
  "evidence": [
    {
      "source": "I:\\SPIDER-CREATOR-ENGINE\\.sce\\acceptance\\foundation-v0.1\\build-output\\hello-sce.pyz",
      "detail": "package created and SHA-256 recorded; functionality remains unverified",
      "observed_at": "2026-10-15T12:23:05.972873+00:00",
      "kind": "artifact"
    },
    {
      "source": "python.zipapp.verify",
      "detail": "declared exit and stdout matched",
      "observed_at": "2026-10-15T12:23:06.044040+00:00",
      "kind": "verification"
    }
  ],
  "unknowns": [
    "Installation was not requested, performed, or verified",
    "Declared fixture check does not establish general application correctness"
  ],
  "started_at": "2026-10-15T12:23:05.948642+00:00",
  "finished_at": "2026-10-15T12:23:06.044069+00:00"
}
```
