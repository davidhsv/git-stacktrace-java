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
    # Regex to capture the main parts of a stack frame line
    # Group 1: Fully qualified method (e.g., com.example.MyClass.myMethod, $Lambda$5/123.run)
    # Group 2: Source info within parentheses (e.g., MyClass.java:123, Native Method, Unknown Source)
    # It intentionally ignores the ~[...] part if present after the closing parenthesis.
    _LINE_RE = re.compile(r"^\s*at\s+([\w$.<>/\-]+)\((.*?)\)") # Allow $, <, >, / and - in method/class names

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

            # Check if it looks like a stack frame line
            # Use regex search instead of startswith to be more flexible
            is_stack_frame = bool(self._LINE_RE.search(stripped_line))

            if is_stack_frame:
                # Once we see the first stack frame, subsequent non-frame lines
                # (like '... N more' or 'Caused by:') are handled below,
                # but we stop adding to the header.
                current_list = stack_lines
                stack_lines.append(line)
            elif stripped_line.startswith("Caused by:") or stripped_line.startswith("Suppressed:"):
                 # Stop processing at the first 'Caused by:' or 'Suppressed:' for simplicity.
                 # A more complex parser could handle nested exceptions.
                 # Add the 'Caused by:' line itself to the header of the *current* exception.
                 if current_list is header_lines: # If we haven't seen 'at' lines yet
                     header_lines.append(line)
                 break # Stop processing this exception block
            elif stripped_line.startswith("..."):
                 # This is part of the stack trace, often indicating omitted frames.
                 # Add it to stack_lines so context isn't lost, although we won't parse it into a Line object.
                 if current_list is stack_lines: # Make sure we've already started stack lines
                    stack_lines.append(line)
                 # If we see "... N more" before any "at" line, it's unusual - treat as header? Or ignore? Ignore for now.
            elif current_list is header_lines:
                # If it's not a stack frame, not 'Caused by', etc., and we are still
                # collecting the header, add it to the header.
                header_lines.append(line)
            # Else: If it's some other unexpected line appearing *after* stack frames started, ignore it.

        # Join header lines (preserve newlines if header was multi-line)
        self.header = "".join(header_lines) # Original lines include newlines if present

        extracted = []
        for line_string in stack_lines:
            # Only try to parse lines that look like stack frames
            if self._LINE_RE.search(line_string.strip()):
                try:
                    extracted.append(self._extract_line(line_string))
                except ParseException as e:
                    # Optionally log skipped lines
                    # print(f"Warning: Skipping line due to parse error: {line_string.strip()} ({e})")
                    pass
            # else: handle '... N more' if needed, e.g., store the count

        self.lines = extracted

        # Raise exception only if *nothing* useful was parsed (no header AND no lines)
        if not self.header.strip() and not self.lines:
            raise ParseException("Failed to parse stacktrace: No header or stack frames found.")
        # It's valid to have a header but no stack lines (e.g., exception in static initializer)


    def _extract_line(self, line_string):
        match = self._LINE_RE.match(line_string.strip())
        if not match:
            raise ParseException(f"Line does not match expected format: {line_string.strip()}")

        full_method, source_info = match.groups()

        # Split the fully qualified method name (e.g., com.example.MyClass.myMethod)
        parts = full_method.split('.')
        if len(parts) < 2:
             # Handle cases like '$Lambda$5/1034627183.run' or potentially just 'method' if classless?
             # Assume format is ClassName.methodName even for complex names
             if len(parts) == 1 and '.' not in full_method: # Very unlikely, maybe just function name?
                 raise ParseException(f"Cannot determine class/method from: {full_method}")
             # If parts = ['$Lambda$5/1034627183', 'run'], class is first part
             function_name = parts[-1]
             class_name = parts[-2] # Might be complex like $Lambda$5/1034627183
             package_parts = parts[:-2] # Might be empty list
        else:
             # Standard case: com.example.MyClass.myMethod
             function_name = parts[-1]
             class_name = parts[-2]
             package_parts = parts[:-2]

        native_method = False
        unknown_source = False
        java_filename = None # The actual filename like MyClass.java
        line_number = None

        # Process the source_info (content within parentheses)
        source_info = source_info.strip()
        if source_info == "Native Method":
            native_method = True
            java_filename = class_name + ".java" # Best guess for filename
        elif source_info == "Unknown Source":
            unknown_source = True
            java_filename = class_name + ".java" # Best guess for filename
        elif ':' in source_info:
            # Might be "FileName.java:LineNumber"
            try:
                file_info, line_no_str = source_info.rsplit(':', 1)
                line_number = int(line_no_str)
                # Use the file_info as the java_filename (could be just Class.java or contain module info)
                java_filename = file_info
            except ValueError:
                # Couldn't split or convert line number to int, treat as Unknown Source
                unknown_source = True
                java_filename = class_name + ".java" # Best guess
        elif source_info.endswith(".java"):
             # Contains a filename but no line number (less common, but possible)
             java_filename = source_info
        else:
             # Some other unexpected format inside parentheses, treat as Unknown Source
             unknown_source = True
             java_filename = class_name + ".java" # Best guess

        # Construct the trace_filename (path-like representation)
        # Use package_parts and the derived java_filename
        # If java_filename already contains slashes (e.g. module info), don't prepend package?
        # For simplicity, let's assume java_filename is just the file name (like Class.java)
        # and construct the path from package_parts.
        # However, if java_filename was extracted, use it directly. Let's refine:
        if java_filename:
             # Use the package path derived from the class and the extracted/guessed filename
             trace_filename = "/".join(package_parts + [java_filename])
        else:
             # Fallback if java_filename couldn't be determined (shouldn't happen with current logic)
             trace_filename = "/".join(package_parts + [class_name + ".java"])


        return Line(trace_filename, line_number, function_name, None, class_name, native_method, unknown_source)

    def _format_line(self, line):
        # Reconstruct the package.path.from.class
        # line.trace_filename is like com/example/MyClass.java
        # line.class_name is like MyClass
        # line.function_name is like myMethod
        # line.line_number is int or None
        # line.java_filename (extracted from trace or guessed) needs to be derived if needed for formatting

        if line.trace_filename:
            split = line.trace_filename.split("/")
            if len(split) > 1:
                path = ".".join(split[:-1])
                actual_filename = split[-1] # e.g., MyClass.java or SomeFile.java
            else:
                path = "" # No package
                actual_filename = line.trace_filename # Should be the filename
        else: # Should not happen if parsing succeeded
            path = "<unknown_path>"
            actual_filename = "<unknown_file>"


        # Construct the full class.method part
        # If path exists, prefix it.
        full_class_method = f"{path}.{line.class_name}.{line.function_name}" if path else f"{line.class_name}.{line.function_name}"


        if line.native_method:
            return f"\tat {full_class_method}(Native Method)\n"
        if line.unknown_source:
            return f"\tat {full_class_method}(Unknown Source)\n"
        if line.line_number is not None:
            # Use the filename derived during parsing (actual_filename might differ from class_name + ".java")
            return f"\tat {full_class_method}({actual_filename}:{line.line_number})\n"
        else:
             # Case where it wasn't native or unknown, but line number is missing (e.g., only filename was present)
             return f"\tat {full_class_method}({actual_filename})\n"

    def format_lines(self):
        return "".join(map(self._format_line, self.lines))

    def file_match(self, trace_filename, git_files):
        # trace_filename is like com/allocadia/planning/model/MyClass.java
        # git_files could be like src/main/java/com/allocadia/planning/model/MyClass.java
        # This logic correctly checks if a git file path ends with the constructed trace path/filename.
        return [f for f in git_files if f.replace('\\', '/').endswith(trace_filename)] # Handle windows paths in git_files



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
