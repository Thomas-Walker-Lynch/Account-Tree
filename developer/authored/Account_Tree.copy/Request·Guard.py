#!/usr/bin/env -S python3 -B
# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Request·Guard - the guard of Account-Tree's Request language.

Started by the gate Account_Tree__Gate·Request, with the gate's real and
effective ids, and with the journal on standard input. It checks the
journal: first with Man-In-Grey's well-formed guard, against the language
definition in Request·Language.py, then with the language's own checks in
Request·GuardCheck.py, which read the account tree from the databases. It
says what it found on standard error, one line per finding, as
<tag>: <message>; the first two lines are name: and version:.

When every check passes, it writes one line to standard output,

  guard Request check passed

and exits 0. That line and that status together are the only verdict the
gate admits a journal on.

Its constraints are the predicates at the top of this file. The account
tree decides what each account can ask; the constraints can narrow that.

Before it imports anything, it checks that every file it could import, in
its own directory and in Man-In-Grey's beside it, and those directories,
are owned by root or by the effective uid's account, and writable by no
other account. A module runs code when it is imported.

Usage: Request·Guard <command>
  help | -h   print this message (also printed when given no arguments)
  check       check the journal on standard input

Exit status: 0 when every check passed, 1 when a check refused the journal,
2 when the journal could not be checked.
"""

# ------------------------------------------------------------------------------
# The constraints: the predicates this guard checks a journal with, besides
# what the account tree records allow. A predicate allows only by answering
# True. As written, every account a person uses can give journals to the gate,
# and the records decide what each can ask.

# constraints begin

def is__allowed_account(user_name):
  "True when the account, the gate's real uid, can give journals to the gate"
  return True

# constraints end
# ------------------------------------------------------------------------------


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

if __name__ == "__main__" and sys.argv[1:] == ["check"]:
  say("name" ,LANGUAGE)
  say("version" ,VERSION)

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
  import Guard·LibraryConstraint   # for the constraints at the top, which can call it by name
  import Request·Language as language_module
  import Request·GuardCheck as guard_check
except ImportError as error:
  say("cannot-start" ,str(error))
  sys.exit(2)


def report(tag ,message):
  say(tag ,Journal.clean(message))

def check():
  report("constraints" ,str(Path(__file__).resolve()))
  try:
    gate_invoking_account = Guard.gate_invoking_account()
  except RuntimeError as error:
    report("cannot-check" ,str(error))
    return 2
  try:
    language_definition = Language.Definition(language_module.NAME ,language_module.DEFINITION)
  except Language.DefinitionError as error:
    report("cannot-check" ,str(error))
    return 2
  status = Guard.check(sys.stdin.buffer.read() ,language_definition ,guard_check ,sys.modules[__name__] ,gate_invoking_account ,report)
  if status == 0:
    sys.stdout.write(f"guard {LANGUAGE} check passed\n")
  return status


# --------------------------------------------------------------------------------
# command line

def print_help():
  print(__doc__.strip())
  return 0

def CLI(argv=None):
  argv = sys.argv[1:] if argv is None else argv
  if not argv or argv[0] in ("help" ,"-h" ,"--help"): return print_help()
  if argv != ["check"]:
    say("usage" ,f"unknown command {Journal.clean(repr(' '.join(argv)))}; run Request·Guard with no arguments for its usage")
    return 2
  return check()


if __name__ == "__main__":
  try:
    sys.exit(CLI())
  except Exception as error:
    say("failed" ,Journal.clean(f"{type(error).__name__}: {error}"))
    sys.exit(2)
