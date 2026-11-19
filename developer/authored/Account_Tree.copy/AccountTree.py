# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
AccountTree - the system accounts as a tree, read from their names

root is at the top of the tree, and a login account is a child of root. Every
account is entered through its parent: root enters a login account through
the system's login programs, and a login account enters its child accounts,
and they theirs, through the request gate. An account's name is its parent's name,
the separator, and its own short name: Thomas·developer·scratch is a child of
Thomas·developer, a child of the login account Thomas, a child of root.

The tree is read from the system accounts' names. Everything here only reads
/etc/passwd, so it runs with the privileges of whoever started the tool.

The separator is the middle dot, U+00B7, two bytes in UTF-8. While existing
system accounts still carry the old separator '_', READ_OLD_SEPARATOR lets a
name without a middle dot be split on its last '_'. Set it to False once the
accounts are renamed; until then, a login account whose own name contains '_'
would be misread as a child account.
"""

import os
from dataclasses import dataclass
from typing import Optional

import SystemAccount as sa
import Kernel
from Kernel import KernelError

SEPARATOR = "·"
OLD_SEPARATOR = "_"
READ_OLD_SEPARATOR = True
NOBODY_UID = 65534


@dataclass
class Account:
  name: str
  uid: int
  home: str

  @property
  def home_exists(self) -> bool:
    return os.path.isdir(self.home)


def from_entry(entry) -> Account:
  return Account(entry.pw_name ,entry.pw_uid ,entry.pw_dir)

def account(name: str) -> Optional[Account]:
  entry = sa.system_account(name)
  return from_entry(entry) if entry else None

def acting_account() -> Account:
  return from_entry(sa.system_account__by_system_uid(os.getuid()))

def is__person_account(entry) -> bool:
  """
  A login account or a child account: an account of a person, not one of
  the system's own services.
  """
  return sa.system_uid__min() <= entry.pw_uid != NOBODY_UID

def split_name(name: str) -> tuple[str ,str]:
  """
  (parent ,short name) of an account name. The parent of a name without a
  separator is root; root itself has no parent.
  """
  if name == "root":
    return ("" ,"root")
  if SEPARATOR in name:
    return tuple(name.rsplit(SEPARATOR ,1))
  if READ_OLD_SEPARATOR and OLD_SEPARATOR in name:
    return tuple(name.rsplit(OLD_SEPARATOR ,1))
  return ("root" ,name)

def list__child_account(parent: str) -> list[Account]:
  """
  The child accounts of parent.
  """
  result = []
  for entry in sa.list__system_account():
    if not is__person_account(entry):
      continue
    if entry.pw_name != parent and split_name(entry.pw_name)[0] == parent:
      result.append(from_entry(entry))
  return result

def child_account__name(parent: str ,short: str) -> str:
  """
  The name for a new child account of parent. A short name may not hold the separator.
  """
  if SEPARATOR in short:
    raise ValueError(f"a short name may not contain '{SEPARATOR}': {short}")
  if parent == "root":
    return short
  return parent + SEPARATOR + short

CURRENT = "."    # as a part of a name typed: the account reached so far, at first the current account
PARENT = ".."    # as a part of a name typed: the parent of the account reached so far

def account_name__expand(name__current: str ,text: str ,is__existing: bool = True) -> str:
  """
  The system account name of the account text names, read from the current
  account, name__current, the account the program runs under. Written as on
  a command line:

    ·                 root
    ·<name>           absolute: <name> below root, as ·Thomas·developer
    <name>            relative: <name> below the current account, as
                      developer, from Thomas, for Thomas·developer
    .                 the current account
    ..                its parent
    ..·<name>         <name> below the parent: a sibling, from Thomas·developer
                      ..·browser is Thomas·browser

  The parts of a name are read in turn, as the parts of a path are: . stays
  where it is and .. goes up one. No account is named . or .., so a part
  that is one of them always has this meaning; valid_name refuses them as
  parts of a name, and systemd refuses them as names.

  A leading separator marks the name absolute, and no account name begins
  with one, as no part of a name is empty; so a text has one reading,
  whatever the current account is. Root's children carry no prefix in
  /etc/passwd, so ·Thomas is Thomas. A trailing separator, which would name
  the accounts below an account rather than the account, is refused, as no
  command takes that yet.

  Raises ValueError when text is not an account name, and, with
  is__existing, when no system account has the name.
  """
  if not text:
    raise ValueError("an account name is not empty")
  if text == SEPARATOR:
    name = "root"
  else:
    is__absolute = text.startswith(SEPARATOR)
    rest = text[1:] if is__absolute else text
    if rest.endswith(SEPARATOR):
      raise ValueError(f"{text} ends with '{SEPARATOR}', which would name the accounts below one; an account is named here")
    if rest.startswith(SEPARATOR) or SEPARATOR + SEPARATOR in rest:
      raise ValueError(f"every part of an account name between the separators '{SEPARATOR}' is not empty: {text}")
    if is__absolute or name__current == "root":
      list__part = []
    else:
      list__part = name__current.split(SEPARATOR)
    for part in rest.split(SEPARATOR):
      if part == CURRENT:
        continue
      if part == PARENT:
        if not list__part:
          raise ValueError(f"{text} goes above root")
        list__part.pop()
        continue
      list__part.append(part)
    name = SEPARATOR.join(list__part) if list__part else "root"
  if is__existing and sa.system_account(name) is None:
    raise ValueError(f"there is no account {name}" + ("" if name == text else f", which {text} names"))
  return name

def account_name__specifier(name: str) -> str:
  """
  The absolute text that names the system account name on a command line,
  the inverse of account_name__expand: · for root, and ·<name> for every
  other account, as ·Thomas·developer.
  """
  return SEPARATOR if name == "root" else SEPARATOR + name

def parent_of(name: str) -> str:
  return split_name(name)[0]

def short_name(name: str) -> str:
  return split_name(name)[1]


# --------------------------------------------------------------------------------
# state

STATE__IN_SESSION = "in session"
STATE__IDLE = "idle"
STATE__OFFLINE = "offline"

def set__session__system_uid() -> set[int]:
  """
  The system uids that have at least one session, as systemd-logind counts
  them: a desktop login, a console login, or a machinectl shell. Empty when
  the sessions cannot be read.
  """
  try:
    return Kernel.set__session__system_uid()
  except KernelError:
    return set()

def state(entry: Account ,set__session: set[int]) -> str:
  """
  in session   the account has a session
  idle         no session, and its home is here
  offline      no session, and its home is not here: it is kept on a storage
               that is not attached
  """
  if entry.uid in set__session:
    return STATE__IN_SESSION
  if not entry.home_exists:
    return STATE__OFFLINE
  return STATE__IDLE
