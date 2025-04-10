# git-stacktrace-java

**Quickly find Git commits related to Java stacktraces.**

---

## 🚀 Installation

Install using `pipx` (recommended):

```shell
pipx install git-stacktrace-java
```

Or using `pip`:

```shell
pip install git-stacktrace-java
```

---

## 🛠 Usage

Copy your stacktrace to clipboard (or pass it via stdin), then run:

```shell
git-stacktrace-java --since 30.days
```

The tool will output recent commits affecting files or code shown in the stacktrace.

### Parameters:

- `--since`: Specify a time range (e.g., `30.days`, `2.weeks`, `24.hours`).

---

## 📖 Example

```shell
git-stacktrace-java --since 30.days < stacktracefile.txt
```
or using the clipboard
```shell
git-stacktrace-java --since 30.days
```

Output:

```
--- Looking up commits... ---

--- Results ---

commit e362f550bd03fc7fdce4be74c12ec953c420ac69
Commit Date: Thu, 27 Mar 2025 17:22:04 -0300
Author:      Voldermort
Subject:     feat(PERF-1176): View Access: hide Edit actual impact button (#18775)
Files Modified:
    - allocadia-core/src/main/java/com/example/ServiceClass.java

commit bd0d748aa3144f68d6795880cf1309aa67ac1b17
Commit Date: Tue, 18 Mar 2025 11:07:04 -0300
Author:      Malfoy
Subject:     chore(PERF-1162): Overload method getActivities (#18733)
Files Modified:
    - allocadia-core/src/main/java/com/example/ServiceClass.java
    - allocadia-core/src/main/java/com/example/ServiceClass.java:118
```

---

## 📌 Features

- Finds recent commits related to stacktrace files and code.
- Supports clipboard and stdin input.
- Simple and fast troubleshooting during deploys.

---

## 💡 Contributing

Feel free to open an issue or submit a pull request!