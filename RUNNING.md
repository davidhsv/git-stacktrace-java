git-stacktrace-java --since 30.days < check_issue.stack

uv run git-stacktrace-java

uv build
pipx install dist/git_stacktrace_java-0.1.0-py3-none-any.whl --force


uv publish
username __token__
password token from here: https://pypi.org/manage/account/