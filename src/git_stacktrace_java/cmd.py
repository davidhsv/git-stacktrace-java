from __future__ import print_function

import argparse
import logging
import os
import select
import sys
# Make sure pyperclip is installed: pip install pyperclip
import pyperclip

import git_stacktrace_java
from git_stacktrace_java import api
from git_stacktrace_java import server
from wsgiref.simple_server import make_server


def main():
    usage = "git-stacktrace-java [<options>] [<RANGE>] [< stacktrace from stdin or clipboard]" # Updated usage hint
    description = "Lookup commits related to a given stacktrace (reads from stdin or clipboard)." # Updated description
    parser = argparse.ArgumentParser(usage=usage, description=description)
    range_group = parser.add_mutually_exclusive_group()
    range_group.add_argument(
        "--since", metavar="<date1>", help="show commits " "more recent than a specific date (from git-log)"
    )
    range_group.add_argument("range", nargs="?", help="git commit range to use")
    range_group.add_argument(
        "--server", action="store_true", help="start a " "webserver to visually interact with git-stacktrace"
    )
    parser.add_argument("--port", default=os.environ.get("GIT_STACKTRACE_PORT", 8080), type=int, help="Server port")
    parser.add_argument(
        "-f",
        "--fast",
        action="store_true",
        help="Speed things up by not running " "pickaxe if the file for a line of code cannot be found",
    )
    parser.add_argument(
        "-b",
        "--branch",
        nargs="?",
        help="Git branch. If using --since, use this to "
        "specify which branch to run since on. Runs on current branch by default",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%s version %s" % (os.path.split(sys.argv[0])[-1], "1.0.0") # Example version
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(format="%(name)s:%(funcName)s:%(lineno)s: %(message)s")
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.server:
        print("Starting httpd on port %s..." % args.port)
        httpd = make_server("", args.port, server.application)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            sys.exit(0)

    if args.since:
        git_range = api.convert_since(args.since, branch=args.branch)
        print("Commit range: %s" % git_range, file=sys.stderr)
    else:
        if args.range is None:
            # If running as server, range isn't needed immediately
            # But if not server, it's an error.
             print("Error: Missing range or --since argument.", file=sys.stderr)
             parser.print_help()
             sys.exit(1)
        git_range = args.range

    if not api.valid_range(git_range):
        print("Error: Found no commits in range '%s'" % git_range, file=sys.stderr)
        sys.exit(1)

    # --- Read input from stdin or clipboard ---
    blob_lines = []
    input_source = "stdin"

    # Check if stdin is connected to a terminal (True) or a pipe/redirect (False)
    if sys.stdin.isatty():
        input_source = "clipboard"
        print("No stdin detected, trying clipboard...", file=sys.stderr)
        if pyperclip is None:
            print("Error: pyperclip module not found. Please install it (`pip install pyperclip`) to use clipboard input.", file=sys.stderr)
            sys.exit(1)
        try:
            clipboard_content = pyperclip.paste()
            if not clipboard_content:
                print("Error: Clipboard is empty.", file=sys.stderr)
                sys.exit(1)
            # Split clipboard content into lines, preserving line endings if possible
            blob_lines = clipboard_content.splitlines(True)
            print(f"Read {len(blob_lines)} lines from clipboard.", file=sys.stderr)
        except Exception as e: # Catch potential pyperclip errors
             print(f"Error reading from clipboard: {e}", file=sys.stderr)
             sys.exit(1)
    else:
        print("Reading stacktrace from stdin...", file=sys.stderr)
        blob_lines = sys.stdin.readlines()
        if not blob_lines:
             print("Error: Received empty input from stdin.", file=sys.stderr)
             sys.exit(1)
        print(f"Read {len(blob_lines)} lines from stdin.", file=sys.stderr)


    # --- Process the stacktrace ---
    try:
        # Assuming parse_trace expects a list of lines
        traceback = api.parse_trace(blob_lines)
        print("\n--- Parsed Traceback ---", file=sys.stderr) # Use stderr for progress
        print(traceback) # Print the parsed representation
        print("--- Looking up commits... ---", file=sys.stderr)

        results = api.lookup_stacktrace(traceback, git_range, fast=args.fast)

        print("\n--- Results ---") # Print results to stdout
        sorted_results = results.get_sorted_results()
        if not sorted_results:
            print("No matches found")
        else:
            for r in sorted_results:
                print("") # Add spacing
                print(r)

    except Exception as e: # Catch parsing or lookup errors
        print(f"\nAn error occurred: {e}", file=sys.stderr)
        if args.debug:
            import traceback as tb
            tb.print_exc() # Print full Python traceback if in debug mode
        sys.exit(1)


if __name__ == "__main__":
    main()