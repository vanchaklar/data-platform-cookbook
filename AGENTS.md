# Contributor guidance

Keep reusable solutions in separate directories under their integration topic.
Each solution owns its Compose file, README, tests and dependency pins. Use small,
reusable examples and synthetic data; never include private data.
Do not imply that a scaffold is a working end-to-end solution.

Use a task branch and append commits; do not rewrite history. Run affected tests.
Keep container ports on loopback, do not commit real credentials, and never silently
reset existing data. Integration tests may create/remove only their own disposable
resources. Report validation stages that could not be executed.
