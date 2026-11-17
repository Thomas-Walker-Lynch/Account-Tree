#!/usr/bin/env -S python3 -B
# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Request·Interpreter - the interpreter of Account-Tree's Request language.

Started by the gate Account_Tree__Gate·Request, with the gate's real and
effective ids, root's, and with the journal on standard input, once the
guard has passed the journal. It executes the journal's request, and writes
to standard error, as <tag>: <message>, a line for each lasting change it
makes. The gate logs the journal's course itself.

When it has played the journal, it writes the journal's result to
descriptor 3, which the gate gives it: a CBOR map of the result's type name
and value, with the descriptors it holds sent beside it; see Man-In-Grey's
Interpreter.write_result. Then it writes one line to standard output,

  interpreter Request journal played

and exits 0. The gate takes the journal as played on that line and that
status together, and on nothing else.

It checks again that the journal is well formed before executing it. It
does not check the constraints or the records; that is the guard's work,
and the gate starts the interpreter only on the guard's verdict.

Before it imports anything, it checks that every file it could import, in
its own directory and in Man-In-Grey's beside it, and those directories,
are owned by root or by the effective uid's account, and writable by no
other account.

Usage: Request·Interpreter <command>
  help | -h   print this message (also printed when given no arguments)
  execute     execute the journal on standard input

Exit status: 0 when the journal was played, 1 when execution failed partway,
2 when the journal could not be read or is not well formed.
"""

import sys ,os
sys.dont_write_bytecode = True

import stat
from pathlib import Path

LANGUAGE = "Request"
VERSION = "4"

DIRPA__HERE = Path(__file__).resolve().parent

def dirpa__Man_In_Grey():
  """
  Man-In-Grey's modules: Man_In_Grey/ beside this file where Account-Tree is
  installed, or the project's Man-In-Grey dependency where it is promoted.
  """
  installed = DIRPA__HERE / "Man_In_Grey"
  if installed.is_dir():
    return installed
  return (DIRPA__HERE.parent.parent / "shared" / "project-dependency" / "Man-In-Grey" / "Man_In_Grey").resolve()

def trusted_owner__problem(fsnodp__checked):
  "None when path is owned by root or the effective uid's account and writable by no other account"
  try:
    st = os.lstat(fsnodp__checked)
  except OSError as error:
    return f"{fsnodp__checked}: {error.strerror}"
  if st.st_uid not in (0 ,os.geteuid()):
    return f"{fsnodp__checked} is owned by uid {st.st_uid}, neither root nor the effective uid's account"
  if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
    return f"{fsnodp__checked} is writable by group or other accounts"
  return None

def list__importable(dirpa):
  "the directory, everything in it, and what its __pycache__ holds"
  result = [dirpa]
  for each in sorted(dirpa.iterdir()):
    result.append(each)
    if each.name == "__pycache__" and each.is_dir() and not each.is_symlink():
      result += sorted(each.iterdir())
  return result

def say(tag ,message):
  print(f"{tag}: {message}" ,file=sys.stderr)

for dirpa in (DIRPA__HERE ,dirpa__Man_In_Grey()):
  try:
    list__checked = list__importable(dirpa)
  except OSError as error:
    say("refused-to-start" ,f"{dirpa}: {error.strerror}")
    sys.exit(2)
  for each in list__checked:
    problem = trusted_owner__problem(each)
    if problem:
      say("refused-to-start" ,problem)
      sys.exit(2)
sys.path.insert(1 ,str(dirpa__Man_In_Grey()))

try:
  import Language
  import Journal
  import Guard
  import Interpreter
  import Request·Language as language_module
  import Request·LibraryInstruction as library_instruction
  import Request·Guard as guard_program
except ImportError as error:
  say("cannot-start" ,str(error))
  sys.exit(2)


def log(tag ,message):
  print(f"{tag}: {Journal.clean(message)}" ,file=sys.stderr ,flush=True)

def execute():
  try:
    gate_invoking_account = Guard.gate_invoking_account()
  except RuntimeError as error:
    log("cannot-execute" ,str(error))
    return 2
  try:
    language_definition = Language.Definition(language_module.NAME ,language_module.DEFINITION)
  except Language.DefinitionError as error:
    log("cannot-execute" ,str(error))
    return 2
  status ,result ,list__fd = Interpreter.interpret(sys.stdin.buffer.read() ,language_definition ,library_instruction ,log ,guard_program ,gate_invoking_account)
  if status != 0:
    return status
  if result is not None:
    try:
      Interpreter.write_result(result ,list__fd)
    except OSError as error:
      log("cannot-return-result" ,f"descriptor {Interpreter.RESULT_FD}: {error.strerror}")
      return 2
  sys.stdout.write(f"interpreter {LANGUAGE} journal played\n")
  return 0


# --------------------------------------------------------------------------------
# command line

def print_help():
  print(__doc__.strip())
  return 0

def CLI(argv=None):
  argv = sys.argv[1:] if argv is None else argv
  if not argv or argv[0] in ("help" ,"-h" ,"--help"): return print_help()
  if argv != ["execute"]:
    say("usage" ,f"unknown command {Journal.clean(repr(' '.join(argv)))}; run Request·Interpreter with no arguments for its usage")
    return 2
  return execute()


if __name__ == "__main__":
  try:
    sys.exit(CLI())
  except Exception as error:
    say("failed" ,Journal.clean(f"{type(error).__name__}: {error}"))
    sys.exit(2)
