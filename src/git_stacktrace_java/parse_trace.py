"""Extract important filenames, lines, functions and code from stacktrace

Currently only supports python stacktraces
"""

from __future__ import print_function

import abc
import logging
import re
import traceback

log = logging.getLogger(__name__)


class ParseException(Exception):
    pass


class Line(object):
    """Track data for each line in stacktrace"""

    def __init__(
        self, filename, line_number, function_name, code, class_name=None, native_method=False, unknown_source=False
    ):
        self.trace_filename = filename
        self.line_number = line_number
        self.function_name = function_name
        self.code = code
        self.class_name = class_name  # Java specific
        self.native_method = native_method  # Java specific
        self.unknown_source = unknown_source  # Java specific
        self.git_filename = None

    def traceback_format(self):
        return (self.trace_filename, self.line_number, self.function_name, self.code)


class Traceback(object, metaclass=abc.ABCMeta):
    def __init__(self, blob):
        self.header = ""
        self.footer = ""
        self.lines = None
        self.extract_traceback(self.prep_blob(blob))

    def prep_blob(self, blob):
        """Cleanup input."""
        # remove empty lines
        if isinstance(blob, list):
            blob = [line for line in blob if line.strip() != ""]
            if len(blob) == 1:
                blob = blob[0].replace("\\n", "\n").split("\n")
        # Split by line
        if isinstance(blob, str):
            lines = blob.split("\n")
        elif isinstance(blob, list):
            if len(blob) == 1:
                lines = blob[0].split("\n")
            else:
                lines = [line.rstrip() for line in blob]
        else:
            message = "Unknown input format"
            log.debug("%s - '%s", message, blob)
            raise ParseException(message)
        return lines

    @abc.abstractmethod
    def extract_traceback(self, lines):
        """Extract language specific traceback"""
        return

    @abc.abstractmethod
    def format_lines(self):
        """format extracted traceback in same way as traceback."""
        return

    def __str__(self):
        return self.header + self.format_lines() + self.footer

    @abc.abstractmethod
    def file_match(self, trace_filename, git_files):
        """How to match a trace_filename to git_files.

        Generally this varies depending on which is a substring of the other
        """
        return


class PythonTraceback(Traceback):
    """Parse Traceback string."""

    FILE_LINE_START = '  File "'

    def extract_traceback(self, lines):
        """Convert traceback string into a traceback.extract_tb format"""
        # filter out traceback lines
        self.header = lines[0] + "\n"
        if lines[-1] and not lines[-1].startswith(" "):
            self.footer = lines[-1] + "\n"
        lines = [line.rstrip() for line in lines if line.startswith("  ")]
        # extract
        extracted = []
        code_line = False
        for i, line in enumerate(lines):
            if code_line:
                code_line = False
                continue
            words = line.split(", ")
            if words[0].startswith(self.FILE_LINE_START):
                if not (words[0].startswith('  File "') and words[1].startswith("line ") and words[2].startswith("in")):
                    message = "Something went wrong parsing stacktrace input."
                    log.debug("%s - '%s'", message, line)
                    raise ParseException(message)
                f = words[0].split('"')[1].strip()
                line_number = int(words[1].split(" ")[1])
                function_name = " ".join(words[2].split(" ")[1:]).strip()
                if len(lines) == i + 1 or lines[i + 1].startswith(self.FILE_LINE_START):
                    # Not all lines have code in the traceback
                    code = None
                else:
                    code_line = True
                    code = str(lines[i + 1].strip())

                try:
                    extracted.append(Line(filename=f, line_number=line_number, function_name=function_name, code=code))
                except IndexError:
                    raise ParseException("Incorrectly extracted traceback information")
        self.lines = extracted
        # Sanity check
        new_lines = traceback.format_list(self.traceback_format())
        new_lines = "\n".join([line.rstrip() for line in new_lines])
        lines = "\n".join(lines)
        if lines != new_lines or not self.lines:
            message = "Incorrectly extracted traceback information"
            logging.debug("%s: original != parsed\noriginal:\n%s\nparsed:\n%s", message, lines, new_lines)
            raise ParseException(message)

    def traceback_format(self):
        return [line.traceback_format() for line in self.lines]

    def format_lines(self):
        lines = self.traceback_format()
        return "".join(traceback.format_list(lines))

    def file_match(self, trace_filename, git_files):
        # trace_filename is substring of git_filename
        return [f for f in git_files if trace_filename.endswith(f)]


class JavaTraceback(Traceback):
    # Regex for format: at com.example.Class.method(File.java:123) | (Native Method) | (Unknown Source)
    _LINE_RE_PAREN = re.compile(r"^\s*at\s+([\w$.<>/\-]+)\((.*?)\)")

    # Regex for format: at com.example.Class.method in File.java:123 | File.java
    # Allows negative line numbers (like -2 for native in some formats)
    _LINE_RE_IN_FULL = re.compile(r"^\s*at\s+([\w$.<>/\-]+)\s+in\s+([^:]+):(-?\d+)\s*$")

    # Regex for format: at com.example.Class.method in File.java (no line number)
    _LINE_RE_IN_NO_LINE = re.compile(r"^\s*at\s+([\w$.<>/\-]+)\s+in\s+([^\s]+)\s*$")

    # Regex for format: at com.example.Class.method (no source info at all)
    _LINE_RE_NO_SOURCE = re.compile(r"^\s*at\s+([\w$.<>/\-]+)\s*$")

    def extract_traceback(self, lines):
        self.header = ""
        self.lines = []
        header_lines = []
        stack_lines = []
        current_list = header_lines # Start collecting header lines

        for i, line in enumerate(lines):
            stripped_line = line.strip()
            if not stripped_line: # Skip empty lines
                 continue

            # Check if it looks like a stack frame line (starts with 'at ')
            # A more robust check might be needed if headers can also start with 'at '
            is_stack_frame = stripped_line.startswith("at ")

            if is_stack_frame:
                current_list = stack_lines
                stack_lines.append(line)
            elif stripped_line.startswith("Caused by:") or stripped_line.startswith("Suppressed:"):
                 if current_list is header_lines:
                     header_lines.append(line)
                 break # Stop processing this exception block
            elif stripped_line.startswith("..."):
                 if current_list is stack_lines:
                    stack_lines.append(line) # Keep context like "... N more"
            elif current_list is header_lines:
                 # Add any other non-empty, non-stack-frame lines to the header
                 header_lines.append(line)
            # Else: Ignore unexpected lines appearing after stack frames started

        # Join header lines (preserve newlines if header was multi-line)
        self.header = "".join(header_lines) # Original lines include newlines if present

        extracted = []
        for line_string in stack_lines:
            stripped = line_string.strip()
            # Only try to parse lines that look like stack frames
            if stripped.startswith("at "):
                try:
                    extracted.append(self._extract_line(line_string))
                except ParseException as e:
                    # Optionally log skipped lines
                    print(f"Warning: Skipping line due to parse error: {stripped} ({e})", file=sys.stderr)
                    pass
            # else: handle '... N more' if needed, e.g., store the count

        self.lines = extracted

        # Raise exception only if *nothing* useful was parsed (no header AND no lines)
        if not self.header.strip() and not self.lines:
            raise ParseException("Failed to parse stacktrace: No header or stack frames found.")
        # Allow header-only exceptions

    def _extract_line(self, line_string):
        stripped_line = line_string.strip()

        match_paren = self._LINE_RE_PAREN.match(stripped_line)
        match_in_full = self._LINE_RE_IN_FULL.match(stripped_line)
        match_in_no_line = self._LINE_RE_IN_NO_LINE.match(stripped_line)
        match_no_source = self._LINE_RE_NO_SOURCE.match(stripped_line) # Try last

        full_method = None
        java_filename = None
        line_number = None
        native_method = False
        unknown_source = False

        # --- Try matching different formats ---
        if match_paren:
            # Format: at com.example.Class.method(SourceInfo)
            full_method, source_info = match_paren.groups()
            source_info = source_info.strip()

            if source_info == "Native Method":
                native_method = True
            elif source_info == "Unknown Source":
                unknown_source = True
            elif ':' in source_info:
                try:
                    file_info, line_no_str = source_info.rsplit(':', 1)
                    line_number = int(line_no_str)
                    java_filename = file_info # e.g., MyClass.java
                except ValueError:
                    unknown_source = True # Corrupted source info
            elif source_info.endswith(".java"): # Filename only
                 java_filename = source_info
                 unknown_source = True # No line number means unknown source location essentially
            else: # Unexpected content in parens
                 unknown_source = True

        elif match_in_full:
             # Format: at com.example.Class.method in File.java:123
            full_method, java_filename, line_no_str = match_in_full.groups()
            try:
                line_number = int(line_no_str)
                # Check for the common native method indicator in this format
                if line_number == -2:
                    native_method = True
                    line_number = None # Store as None conceptually, flag set
            except ValueError: # Should not happen with regex, but safety first
                unknown_source = True
                line_number = None

        elif match_in_no_line:
            # Format: at com.example.Class.method in File.java
            full_method, java_filename = match_in_no_line.groups()
            unknown_source = True # No line number

        elif match_no_source:
             # Format: at com.example.Class.method
            full_method = match_no_source.group(1)
            unknown_source = True # No source info provided

        else:
            raise ParseException(f"Line does not match any known format: {stripped_line}")

        # --- Common parsing logic for full_method ---
        parts = full_method.split('.')
        if len(parts) < 2:
             if len(parts) == 1 and '.' not in full_method:
                 raise ParseException(f"Cannot determine class/method from: {full_method}")
             # Handles Class$InnerClass.method or complex names like $Lambda$5/123.run
             function_name = parts[-1]
             class_name = parts[-2] # May include $ or /
             package_parts = parts[:-2]
        else:
             # Standard: com.example.Class.method
             function_name = parts[-1]
             class_name = parts[-2]
             package_parts = parts[:-2]

        # --- Determine trace_filename (path/to/File.java) ---
        # Use extracted java_filename if available, otherwise guess from class_name
        if not java_filename:
            # Guess filename if not provided or if source was unknown/native
            # Use simple class name part (before any $ for inner classes) for the .java file name
            base_class_name = class_name.split('$')[0]
            java_filename = base_class_name + ".java" # Best guess

        # Construct the path-like trace_filename
        trace_filename = "/".join(package_parts + [java_filename])

        return Line(trace_filename, line_number, function_name, None, class_name, native_method, unknown_source)


    def _format_line(self, line):
        # Reconstruct the line based on parsed info, aiming for a consistent format.
        # We'll use the original format with parentheses as the canonical output.

        if line.trace_filename:
            split = line.trace_filename.split("/")
            if len(split) > 1:
                path = ".".join(split[:-1])
                actual_filename = split[-1] # e.g., MyClass.java or SomeFile.aj
            else:
                path = "" # No package
                actual_filename = line.trace_filename # Should be the filename
        else: # Fallback
            path = "<unknown_path>"
            actual_filename = "<unknown_file>"

        # Construct the full class.method part
        full_class_method = f"{path}.{line.class_name}.{line.function_name}" if path else f"{line.class_name}.{line.function_name}"

        # Prioritize flags for formatting
        if line.native_method:
            # Always format detected native methods this way, regardless of original format
            return f"\tat {full_class_method}(Native Method)\n"
        if line.unknown_source or line.line_number is None:
             # Treat missing line number as Unknown Source for formatting
             return f"\tat {full_class_method}(Unknown Source)\n" # Use Unknown Source if line number missing
             # Alternative: could format as f"\tat {full_class_method}({actual_filename})\n" if line_number is None but filename exists
        else:
            # Format with filename and line number
            return f"\tat {full_class_method}({actual_filename}:{line.line_number})\n"

    def format_lines(self):
        return "".join(map(self._format_line, self.lines))

    def file_match(self, trace_filename, git_files):
        # trace_filename is like com/allocadia/planning/model/MyClass.java
        # git_files could be like src/main/java/com/allocadia/planning/model/MyClass.java
        return [f for f in git_files if f.replace('\\', '/').endswith(trace_filename)] # Handle windows paths



class JavaScriptTraceback(Traceback):
    # This class matches a stacktrace that looks similar to https://v8.dev/docs/stack-trace-api

    def extract_traceback(self, lines):
        if not lines[0].startswith("\t"):
            self.header = lines[0] + "\n"
        lines = [line for line in lines if line.startswith("\t")]
        extracted = []
        for line in lines:
            extracted.append(self._extract_line(line))
        self.lines = extracted
        if not self.lines:
            raise ParseException("Failed to parse stacktrace")

    def _extract_line(self, line_string):
        pattern = r"\tat\s(?P<symbol>[^\s(]*)?(?:\s*)?\(?(?P<path>[^\s\?]+)(?:\S*)?\:(?P<line>\d+):(?:\d+)\)?"
        result = re.match(pattern, line_string)

        if result:
            frame = result.groupdict()
        else:
            log.debug("Failed to parse frame %s", line_string)
            raise ParseException

        return Line(frame.get("path"), frame.get("line"), frame.get("symbol"), None)

    def traceback_format(self):
        return [line.traceback_format() for line in self.lines]

    def format_lines(self):
        lines = self.traceback_format()
        return "".join(traceback.format_list(lines))

    def file_match(self, trace_filename, git_files):
        return [f for f in git_files if trace_filename.endswith(f)]


def parse_trace(traceback_string):
    languages = [PythonTraceback, JavaTraceback, JavaScriptTraceback]
    for language in languages:
        try:
            return language(traceback_string)
        except ParseException:
            log.debug("Failed to parse as %s", language)
            # Try next language
            continue
    raise ParseException("Unable to parse traceback")
