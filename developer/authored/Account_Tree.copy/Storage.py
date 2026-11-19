# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Storage - the work functions for storage databases

A storage is a persistent storage device that keeps accounts' data: the disk
inside the machine, or a drive plugged in. A work function is given a storage
by its root, the directory it is mounted at: / for the disk the system runs
from. Account-Tree keeps its files there in one directory, the Account-Tree
directory, <storage root>/home/Account-Tree, which holds the storage database
and account-data, the storage accounts' homes. Common.dirpa__Account_Tree
gives its path.

Which storage accounts are the same accounts as system accounts here is
recorded in the system map of the system database, and attach mounts exactly
the accounts it lists.
"""

import os ,stat ,shutil ,subprocess
from uuid import uuid4
from pathlib import Path

import Database
import Kernel
from Common import DIRPA__HOME ,SEPARATOR ,BRANCH_MARK ,act ,valid_name ,dirp__storage__problem ,dirpa__Account_Tree ,host_name
from System import open_system_database ,DATABASE_UID__FLOOR
import SameAccount

# A storage database gives out database uids counting down from
# DATABASE_UID__FIRST, while systems give out system uids counting up from low
# numbers. See "Limits of uids" in the design document.
DATABASE_UID__FIRST = 1_999_999_999


def open_storage_database(dirp__storage ,log):
  problem = dirp__storage__problem(dirp__storage)
  if problem:
    log.error(str(dirp__storage) ,problem); return None
  return Database.Database.open(Database.fpa__storage_database(dirpa__Account_Tree(dirp__storage)) ,"storage")

def system_map__unplugged(system_db ,storage_db):
  return system_db.rows("SELECT * FROM system_map WHERE database_uuid = ? AND state = 'unplugged' ORDER BY system_account__name",
                        (storage_db.uuid(),))

def system_map__in_use(system_db ,storage_db):
  return system_db.rows("SELECT * FROM system_map WHERE database_uuid = ? AND state = 'in use' ORDER BY system_account__name",
                        (storage_db.uuid(),))


# --------------------------------------------------------------------------------
# storage make, show, delete

def storage__make(dirp__storage ,log ,preview):
  problem = dirp__storage__problem(dirp__storage)
  if problem:
    log.error(str(dirp__storage) ,problem); return
  dirp__Account_Tree = dirpa__Account_Tree(dirp__storage)
  dirp__home = dirp__Account_Tree.parent
  filep__database = Database.fpa__storage_database(dirp__Account_Tree)
  if filep__database.exists():
    db = Database.Database.open(filep__database ,"storage")
    log.line("kept" ,str(filep__database) ,f"a storage database exists, database uuid {db.uuid()}")
  else:
    for dirp__each ,mode in ((dirp__home ,0o755) ,(dirp__Account_Tree ,0o700)):
      if not dirp__each.is_dir():
        if not act(log ,preview ,str(dirp__each) ,os.mkdir ,dirp__each ,mode): return
        if not act(log ,preview ,str(dirp__each) ,os.chmod ,dirp__each ,mode): return
        log.line("made" ,str(dirp__each) ,f"mode {mode:04o}")
    db = Database.Database.make(filep__database ,"storage" ,preview)
    # a database uuid is drawn at random; the one drawn in a preview is thrown away
    log.line("made" ,str(filep__database) ,"a new database uuid" if preview else f"database uuid {db.uuid()}")
  dirp__account_data = Database.dirp__account_data(dirp__Account_Tree)
  if dirp__account_data.is_dir():
    log.line("kept" ,str(dirp__account_data))
  else:
    if not act(log ,preview ,str(dirp__account_data) ,os.mkdir ,dirp__account_data ,0o700): return
    if not act(log ,preview ,str(dirp__account_data) ,os.chmod ,dirp__account_data ,0o700): return
    log.line("made" ,str(dirp__account_data) ,"root only, mode 0700")

def storage__show(dirp__storage):
  problem = dirp__storage__problem(dirp__storage)
  if problem:
    print(f"Error: {problem}"); return 1
  db = Database.Database.open(Database.fpa__storage_database(dirpa__Account_Tree(dirp__storage)) ,"storage")
  d = db.identity()
  print(f"storage   database uuid {d['database_uuid']}")
  if d["branch_of"]:
    print(f"branch    of database {d['branch_of']}, after series {d['branch__after_series']}")
  print(f"file      {db.path}")
  print(f"series    {d['series']}  head {d['head_hash'][:16]}")
  print(f"made      {d['created']}")
  print(f"changed   {db.last_change()}")
  print("standard  " + " ".join(r["version"] for r in db.rows("SELECT version FROM standard")))
  mapped ,unplugged = {} ,{}
  if Database.FPA__SYSTEM_DATABASE.is_file():
    system_db = Database.Database.open(Database.FPA__SYSTEM_DATABASE ,"system")
    mapped = {m["database_uid"]: m for m in system_map__in_use(system_db ,db)}
    unplugged = {m["database_uid"]: m for m in system_map__unplugged(system_db ,db)}
  print("storage accounts")
  for a in db.rows("SELECT * FROM account ORDER BY name"):
    m = mapped.get(a["database_uid"])
    here = f"system account {m['system_account__name']}, system uid {m['system_uid']}" if m else "no system account here"
    if not m and a["database_uid"] in unplugged:
      here = f"system account {unplugged[a['database_uid']]['system_account__name']} when plugged in"
    print(f"  {a['name']:<28}database uid {a['database_uid']:<12}{a['state']:<10}{here}")
  for n in db.rows("SELECT * FROM system_seen ORDER BY first"):
    print(f"seen by   system {n['system_uuid']}  first {n['first']}  last {n['last']}")
  problem = db.verify()
  print("verify    " + ("ok" if not problem else "; ".join(problem)))
  return 1 if problem else 0

def storage__delete(dirp__storage ,delete_account_data ,forget_other_systems ,log ,preview):
  """
  Undo on this system what Account-Tree did for the storage database on the
  storage whose root is dirp__storage, then delete its Account-Tree directory.
  Every check is made before anything is changed; a check that fails stops the
  command with nothing changed.
  """
  problem = dirp__storage__problem(dirp__storage)
  if problem:
    log.error(str(dirp__storage) ,problem); return
  dirp__Account_Tree = dirpa__Account_Tree(dirp__storage)
  dirp__account_data = Database.dirp__account_data(dirp__Account_Tree)
  filep__database = Database.fpa__storage_database(dirp__Account_Tree)
  if not filep__database.is_file():
    log.line("kept" ,str(dirp__Account_Tree) ,"no storage database here; nothing to delete"); return
  db = Database.Database.open(filep__database ,"storage")
  system_db = Database.Database.open(Database.FPA__SYSTEM_DATABASE ,"system") if Database.FPA__SYSTEM_DATABASE.is_file() else None
  this_system__uuid = system_db.uuid() if system_db else None
  # the rows of this database here, unplugged ones too, which delete retires
  in_use = system_db.rows("SELECT * FROM system_map WHERE database_uuid = ? AND state IN ('in use' ,'unplugged')"
                          " ORDER BY system_account__name" ,(db.uuid(),)) if system_db else []
  account_name = {a["database_uid"]: a["name"] for a in db.rows("SELECT database_uid ,name FROM account")}

  # ---- checks
  problem = []
  if not forget_other_systems:
    for n in db.rows("SELECT * FROM system_seen WHERE system_uuid IS NOT ?" ,(this_system__uuid,)):
      problem.append(f"system {n['system_uuid'][:8]} has system accounts for storage accounts of this database, and its"
                     " system map would name a database that no longer exists; give the keyword forget-other-systems"
                     " to delete anyway")
  in_session = Kernel.set__session__system_uid()
  for m in in_use:
    if m["system_uid"] in in_session:
      problem.append(f"{m['system_account__name']} has a login session")
  for dirp__mount_point in Kernel.list__mount_point():
    if dirp__mount_point.startswith(str(dirp__Account_Tree) + "/"):
      problem.append(f"{dirp__mount_point} is a mount point inside {dirp__Account_Tree}")
  for entry in sorted(dirp__Account_Tree.iterdir()):
    if entry.name != "account-data" and not entry.name.startswith("database.sqlite3"):
      problem.append(f"{entry} is not Account-Tree's")
  list__holding_file = []
  if dirp__account_data.is_dir():
    for entry in sorted(dirp__account_data.iterdir()):
      if entry.name not in account_name.values():
        problem.append(f"{entry} is not the home of a storage account of this database")
      elif entry.is_dir() and any(entry.iterdir()):
        list__holding_file.append(entry.name)
  if list__holding_file and not delete_account_data:
    problem.append("these homes hold files: " + ", ".join(list__holding_file) + "; give the keyword delete-account-data to delete them too")
  if problem:
    for p in problem: log.error(str(dirp__Account_Tree) ,p)
    log.line("kept" ,str(dirp__Account_Tree) ,"nothing was changed")
    return

  # ---- this system's system accounts for its storage accounts
  for m in in_use:
    if not SameAccount.same_account__end(m ,system_db ,dirp__Account_Tree ,account_name.get(m["database_uid"] ,"?") ,log ,preview):
      log.line("stopped" ,str(dirp__Account_Tree) ,"nothing further was changed"); return

  # ---- files
  if dirp__account_data.is_dir():
    count_of__home = sum(1 for _ in dirp__account_data.iterdir())
    if not act(log ,preview ,str(dirp__account_data) ,shutil.rmtree ,dirp__account_data): return
    log.line("deleted" ,str(dirp__account_data) ,f"{count_of__home} home" + ("" if count_of__home == 1 else "s"))
  short ,database_uuid = db.short() ,db.uuid()
  db.close()
  for entry in sorted(dirp__Account_Tree.iterdir()):
    if entry.name.startswith("database.sqlite3"):
      if not act(log ,preview ,str(entry) ,entry.unlink): return
      log.line("deleted" ,str(entry) ,f"database {short}" if entry.name == "database.sqlite3" else None)
  if not act(log ,preview ,str(dirp__Account_Tree) ,dirp__Account_Tree.rmdir): return
  log.line("deleted" ,str(dirp__Account_Tree))

  # ---- its record as a removable storage
  if system_db is not None:
    import StoragePlug
    for r in system_db.rows("SELECT * FROM storage_device WHERE database_uuid = ? AND state = 'registered'" ,(database_uuid,)):
      StoragePlug.unregister(r["storage_name"] ,log ,preview)


# --------------------------------------------------------------------------------
# account make

# --------------------------------------------------------------------------------
# a home brought in from outside Account-Tree

# extended attributes that hold an ACL, whose entries name uids and gids
LIST__ACL_XATTR = ("system.posix_acl_access" ,"system.posix_acl_default")
# how many offending files a refused import lists; the rest are counted
COUNT_OF__OFFENDER_LISTED = 40

def home__offender(dirpa__source ,set__uid ,set__gid):
  """
  Walk the directory tree at dirpa__source and return, for each file that
  keeps it from being imported as one account's home, its path and why: an
  owner not in set__uid, a group not in set__gid, an ACL, or a file system
  mounted below. Each home is mounted with one uid and one gid mapped, its
  account's, so a file of any other id would show as nobody on a system
  whose ids differ from this one's.
  """
  list__offender = []
  dev = os.lstat(dirpa__source).st_dev
  def check(path ,st):
    if st.st_dev != dev:
      list__offender.append((path ,"a file system mounted below; unmount it")); return False
    if st.st_uid not in set__uid:
      list__offender.append((path ,f"owned by uid {st.st_uid}"))
    if st.st_gid not in set__gid:
      list__offender.append((path ,f"group gid {st.st_gid}"))
    if not stat.S_ISLNK(st.st_mode):
      try:
        name_list = os.listxattr(path ,follow_symlinks=False)
      except OSError:
        name_list = []
      if any(n in LIST__ACL_XATTR for n in name_list):
        list__offender.append((path ,"an ACL"))
    return True
  def walk(dirpa):
    try:
      entry_list = list(os.scandir(dirpa))
    except OSError as error:
      list__offender.append((dirpa ,f"cannot be read: {error.strerror}")); return
    for e in entry_list:
      try:
        st = e.stat(follow_symlinks=False)
      except OSError as error:
        list__offender.append((e.path ,f"cannot be read: {error.strerror}")); continue
      if check(e.path ,st) and stat.S_ISDIR(st.st_mode):
        walk(e.path)
  check(str(dirpa__source) ,os.lstat(dirpa__source))
  walk(str(dirpa__source))
  return list__offender

def home__owner_set(dirpa__source ,database_uid ,log):
  """
  Give every file at dirpa__source to database uid, owner and group, keeping
  each file's mode: the kernel clears the setuid and setgid bits of a file
  whose owner changes, and they are put back. Returns the count of files changed.
  """
  count = 0
  def give(path ,st):
    nonlocal count
    if st.st_uid == database_uid and st.st_gid == database_uid: return
    os.chown(path ,database_uid ,database_uid ,follow_symlinks=False)
    if not stat.S_ISLNK(st.st_mode) and os.lstat(path).st_mode != st.st_mode:
      os.chmod(path ,stat.S_IMODE(st.st_mode))
    count += 1
  def walk(dirpa):
    for e in os.scandir(dirpa):
      st = e.stat(follow_symlinks=False)
      give(e.path ,st)
      if stat.S_ISDIR(st.st_mode):
        walk(e.path)
  give(str(dirpa__source) ,os.lstat(dirpa__source))
  walk(str(dirpa__source))
  return count

def home__import(dirp__source ,dirpa__home ,database_uid ,log ,preview):
  """
  Bring the directory tree at dirp__source in as the home at dirpa__home, the
  storage account with database_uid not yet recorded. Every file must belong
  to the directory's own owner and group, or already to database_uid; when
  any does not, the offenders are listed and nothing is changed. Otherwise
  every file is given to database_uid, and the tree is moved: renamed when it
  is on the storage's file system, moved by mv otherwise, which copies it and
  then deletes the source. Returns True when the home is in place, or would be.

  A run stopped part way can be run again: files already given to the
  database uid pass the check, and a source already at dirpa__home is not
  moved. The database uid is the next one down, the same again as long as no
  other storage account is made in between.
  """
  dirpa__source = Path(os.path.abspath(dirp__source))
  if dirpa__source.is_symlink() or not dirpa__source.is_dir():
    log.error(str(dirpa__source) ,"not a directory"); return False
  if Kernel.is__mount_point(dirpa__source):
    log.error(str(dirpa__source) ,"is a mount point; give the directory mounted there, on its own storage"); return False
  in_place = dirpa__source == dirpa__home
  if not in_place and (dirpa__home.exists() or dirpa__home.is_symlink()):
    log.error(str(dirpa__home) ,"exists already"); return False
  if dirpa__home.parent in [dirpa__source] + list(dirpa__source.parents) and not in_place:
    log.error(str(dirpa__source) ,"holds account-data itself"); return False
  st = os.lstat(dirpa__source)
  if st.st_uid == 0:
    log.error(str(dirpa__source) ,"is owned by root; give the home of the account, owned by it"); return False
  set__uid = {st.st_uid ,database_uid}
  set__gid = {st.st_gid ,database_uid}
  list__offender = home__offender(dirpa__source ,set__uid ,set__gid)
  if list__offender:
    for path ,why in list__offender[:COUNT_OF__OFFENDER_LISTED]:
      log.error(path ,why)
    more = len(list__offender) - COUNT_OF__OFFENDER_LISTED
    if more > 0:
      log.error(f"{more} more" ,"files offend in the same ways")
    log.line("kept" ,str(dirpa__source) ,f"not imported: every file must be owned by uid {st.st_uid} with group"
             f" gid {st.st_gid}, and carry no ACL; fix those listed and run it again")
    return False
  log.line("checked" ,str(dirpa__source) ,f"every file is owned by uid {st.st_uid}, group gid {st.st_gid}, with no ACL")
  if preview:
    log.line("changed owner" ,str(dirpa__source) ,f"every file to database uid {database_uid}, owner and group")
    if not in_place:
      log.line("moved" ,str(dirpa__source) ,f"to {dirpa__home}")
    return True
  try:
    count = home__owner_set(dirpa__source ,database_uid ,log)
  except OSError as error:
    log.error(str(error.filename or dirpa__source) ,f"owner not changed: {error.strerror}; nothing is recorded,"
              " and running it again carries on"); return False
  log.line("changed owner" ,str(dirpa__source) ,f"{count} file" + ("" if count == 1 else "s") + f" to database uid {database_uid}")
  if not in_place:
    if os.lstat(dirpa__home.parent).st_dev == st.st_dev:
      os.rename(dirpa__source ,dirpa__home)
      log.line("moved" ,str(dirpa__source) ,f"to {dirpa__home}, renamed on the same file system")
    else:
      # mv copies, keeping owners, modes, times and extended attributes, then deletes the source
      result = subprocess.run(["mv" ,"-T" ,str(dirpa__source) ,str(dirpa__home)] ,capture_output=True ,text=True)
      if result.returncode != 0:
        log.error(str(dirpa__source) ,f"mv failed: {result.stderr.strip()}; the source is kept where mv had not"
                  f" finished, and {dirpa__home} holds what was copied"); return False
      log.line("moved" ,str(dirpa__source) ,f"to {dirpa__home}, copied by mv to another file system and the source deleted")
  # the home keeps its mode: a group-readable home, such as one shared by group, stays so
  return True

def account__make(dirp__storage ,name ,database_uid ,parent ,make_system_account ,log ,preview ,dirp__source=None):
  """
  Make a storage account in the storage database of the storage whose root is
  dirp__storage, with its home in account-data. Its parent is the account whose name its own begins with,
  before the last '·', or the one given; an account with no '·' in its name
  is a child of root. With make_system_account, also make a system account of
  the same name and record that the two are the same account.

  Given dirp__source, an existing home, it is brought in as the account's
  home by home__import, in place of an empty one. The account is recorded only once
  the home is in place.
  """
  problem = valid_name(name)
  if problem:
    log.error(name ,problem); return
  db = open_storage_database(dirp__storage ,log)
  if db is None: return
  if db.row("SELECT 1 FROM account WHERE name = ?" ,(name,)):
    log.line("kept" ,f"storage account {name}" ,"already in this database"); return
  if parent is None and SEPARATOR in name:
    parent = name.rsplit(SEPARATOR ,1)[0]
  if parent is not None and not name.startswith(parent + SEPARATOR):
    log.error(name ,f"the name of a child account of {parent} begins with '{parent}{SEPARATOR}'"); return
  parent_row = db.row("SELECT database_uid FROM account WHERE name = ?" ,(parent,)) if parent else None
  parent__database_uid = parent_row["database_uid"] if parent_row else None

  if database_uid is None:
    # the next database uid down from the lowest given out in the band; one
    # kept with the keyword uid lies outside the band and does not move the count
    lowest = db.row("SELECT MIN(database_uid) AS m FROM database_uid WHERE database_uid >= ?",
                    (DATABASE_UID__FLOOR,))["m"]
    database_uid = DATABASE_UID__FIRST if lowest is None else lowest - 1
    if database_uid < DATABASE_UID__FLOOR:
      log.error(name ,"this database has given out every database uid in its band"); return
  elif db.row("SELECT 1 FROM database_uid WHERE database_uid = ?" ,(database_uid,)):
    log.error(name ,f"database uid {database_uid} has been given out before"); return

  dirp__home = Database.dirp__account_data(dirpa__Account_Tree(dirp__storage)) / name
  if dirp__source is not None:
    if not home__import(dirp__source ,dirp__home ,database_uid ,log ,preview): return
  elif dirp__home.exists() and dirp__home.stat().st_uid != database_uid:
    log.error(str(dirp__home) ,f"exists, owned by uid {dirp__home.stat().st_uid}, not database uid {database_uid}"); return

  stamp = Database.now()
  with db.transaction(f"make storage account {name}" ,preview) as t:
    t.execute("INSERT INTO database_uid(database_uid ,state) VALUES (? ,'in use')" ,(database_uid,))
    t.execute("INSERT INTO account(database_uid ,name ,parent__database_uid ,parent_name ,state ,created ,changed)"
      " VALUES (? ,? ,? ,? ,'active' ,? ,?)" ,(database_uid ,name ,parent__database_uid ,parent ,stamp ,stamp))
  log.line("made" ,f"storage account {name}" ,f"database uid {database_uid}" + (f", child of {parent}" if parent else ", child of root"))
  if dirp__source is not None:
    mode = "its mode kept" if preview else f"mode {stat.S_IMODE(os.lstat(dirp__home).st_mode):04o}"
    log.line("kept" ,str(dirp__home) ,f"imported home, owned by database uid {database_uid}, {mode}")
  elif dirp__home.exists():
    log.line("kept" ,str(dirp__home) ,"existing home, owned by its database uid")
  else:
    if not act(log ,preview ,str(dirp__home) ,os.mkdir ,dirp__home ,0o700): return
    if not act(log ,preview ,str(dirp__home) ,os.chown ,dirp__home ,database_uid ,database_uid): return
    if not act(log ,preview ,str(dirp__home) ,os.chmod ,dirp__home ,0o700): return
    log.line("made" ,str(dirp__home) ,f"owned by database uid {database_uid}, mode 0700")

  if make_system_account:
    if preview:
      # the storage account was not made, so the system map could not name it;
      # say what would be done
      log.line("made system account" ,name ,"with the next free system uid in this system's range")
      log.line("mapped" ,f"{name} is {name}" ,"in the system map")
      return
    system_db = open_system_database(log)
    if system_db is None: return
    SameAccount.same_account__map(system_db ,db ,name ,name ,True ,log ,preview)


# --------------------------------------------------------------------------------
# continuity and branches

def continuity(system_db ,db):
  """
  How the storage database's record relates to the heads this system has seen
  of it. Returns (kind ,seen row):
    new         this system has seen no head of it
    forward     its record holds the last head seen: it has moved on since
    backwards   its head is one seen earlier: an older copy
    sideways    its record holds an earlier head seen, not the last one: a branch,
                or an older copy whose head this system never saw
    unrelated   its record holds no head this system has seen
  The seen row is the last head seen that its record holds, if any.
  """
  seen = system_db.rows("SELECT * FROM storage_head__seen WHERE database_uuid = ? ORDER BY id" ,(db.uuid(),))
  if not seen:
    return "new" ,None
  if db.has__head(seen[-1]["series"] ,seen[-1]["head_hash"]):
    return "forward" ,seen[-1]
  series ,head_hash = db.head()
  for s in reversed(seen):
    if (s["series"] ,s["head_hash"]) == (series ,head_hash):
      return "backwards" ,s
  for s in reversed(seen):
    if db.has__head(s["series"] ,s["head_hash"]):
      return "sideways" ,s
  return "unrelated" ,None

def storage__branch(system_db ,db ,dirp__Account_Tree ,log ,preview):
  """
  Make the storage database a branch: give it a new database uuid, record the
  database it came from and the head they parted after, and make a system
  account <name>~<eight hex digits> for each storage account that has a system
  account on the line it came from. Both lines can then be attached at once.
  """
  parent_uuid = db.uuid()
  kind ,seen = continuity(system_db ,db)
  after_series ,after_head = (seen["series"] ,seen["head_hash"]) if seen else (0 ,Database.genesis_hash("storage" ,db.identity()["genesis_uuid"]))
  in_use = system_map__in_use(system_db ,db)
  new_uuid = str(uuid4())
  with db.transaction(f"branch from database {parent_uuid[:8]} after series {after_series}" ,preview) as t:
    t.execute("UPDATE identity SET database_uuid = ? ,branch_of = ? ,branch__after_series = ? ,branch__after_head = ?",
              (new_uuid ,parent_uuid ,after_series ,after_head))
  # the branch is named by the hash of the transaction that made it, which no
  # other branch has; in a preview it is not known
  suffix = "<8 hex>" if preview else db.head()[1][:8]
  log.line("branched" ,f"database {parent_uuid[:8]}",
           f"{'a new database uuid' if preview else 'now database ' + new_uuid[:8]}, after series {after_series}, {kind}")
  for m in in_use:
    a = db.row("SELECT name FROM account WHERE database_uid = ?" ,(m["database_uid"],))
    if a is None: continue
    name = f"{m['system_account__name']}{BRANCH_MARK}{suffix}"
    if preview:
      log.line("made system account" ,name ,"with the next free system uid in this system's range")
      log.line("mapped" ,f"{name} is {a['name']}" ,"of the branch")
      continue
    SameAccount.same_account__map(system_db ,db ,name ,a["name"] ,True ,log ,preview)


# --------------------------------------------------------------------------------
# attach and detach

def attach(dirp__storage ,branch ,log ,preview):
  """
  Mount the home of each storage account that the system map makes the same
  account as a system account here, at /home/<system account>.

  The storage's record is compared with the heads this system has seen of it.
  A storage gone back to an older copy, or sideways to a branch, is attached
  with a warning: no one is kept from working. Given branch, the storage is
  first made a branch of its own, with its own system accounts, so that it and
  the line it came from can both be attached. A storage whose homes are
  already mounted from another copy of it is refused, with that advice.
  """
  system_db = open_system_database(log)
  if system_db is None: return
  db = open_storage_database(dirp__storage ,log)
  if db is None: return
  dirp__Account_Tree = dirpa__Account_Tree(dirp__storage)
  problem = db.verify()
  if problem:
    for p in problem: log.error(str(db.path) ,p)
    return
  log.line("found" ,f"database {db.short()}" ,f"series {db.head()[0]}, chain verified")

  # a removable storage plugged in again: make again the system accounts its
  # unplug deleted, before anything reads the rows in use
  set__promised = set()
  dict__group_later = {}
  dict__share_skipped = {}
  count_of__replugged = sum(1 for m in system_map__unplugged(system_db ,db)
                            if SameAccount.same_account__replug(system_db ,m ,log ,preview ,set__promised ,dict__group_later
                                                                ,dict__share_skipped ,db))
  # supplementary groups that are own groups of accounts made after it
  for name ,list__group in dict__group_later.items():
    list__now = [g for g in list__group if preview or SameAccount.sa.system_group(g) is not None]
    list__gone = [g for g in list__group if g not in list__now]
    if list__now and act(log ,preview ,name ,SameAccount.sa.system_account__group_add ,name ,list__now):
      log.line("set" ,name ,"member again of " + ", ".join(list__now))
    if list__gone:
      log.line("warning" ,name ,"no longer in " + ", ".join(list__gone) + ", which this system no longer has")

  if branch:
    storage__branch(system_db ,db ,dirp__Account_Tree ,log ,preview)
    if preview:
      log.line("mounted" ,"the branch's homes" ,"at /home/<system account>~<8 hex>")
      return

  in_use = system_map__in_use(system_db ,db)
  if preview and count_of__replugged:
    # their rows are put back in use only when the preview's changes are made
    log.line("mounted" ,f"the homes of those {count_of__replugged}" ,"at /home/<system account>, once their system accounts are made")
  if not in_use:
    if not (preview and count_of__replugged):
      log.line("skipped" ,str(dirp__Account_Tree) ,"no storage account of this database is the same account as a system account here")
    return

  # the same database attached twice would mount two homes at one place
  for m in in_use:
    a = db.row("SELECT name FROM account WHERE database_uid = ?" ,(m["database_uid"],))
    dirpa__target ,_ = SameAccount.mount_target(m)
    dirp__source = Database.dirp__account_data(dirp__Account_Tree) / (a["name"] if a else "")
    if Kernel.is__mount_point(dirpa__target) and not SameAccount.is__mounted_from(dirpa__target ,dirp__source):
      log.error(str(dirpa__target) ,"already mounted from another copy of this database, or from something else;"
                " detach that, or attach this storage with the keyword branch. Nothing was mounted.")
      return

  kind ,seen = continuity(system_db ,db)
  series = db.head()[0]
  if kind == "new":
    log.line("found" ,f"database {db.short()}" ,"not attached here before")
  elif kind == "forward":
    log.line("found" ,f"database {db.short()}",
             f"holds the head last seen here, series {seen['series']}; {series - seen['series']} transactions since")
  elif kind == "backwards":
    log.line("warning" ,f"database {db.short()}",
             f"its head, series {series}, is the one seen here at {seen['seen']}, and another state of this"
             " database has been attached here since: this is an older copy, or the other line of a branch."
             " Merging the two lines is by hand")
  elif kind == "sideways":
    log.line("warning" ,f"database {db.short()}",
             f"went sideways: it holds the head seen here at series {seen['series']}, but not the last one;"
             " it is a branch, or an older copy. Merging the two lines is by hand")
  else:
    log.line("warning" ,f"database {db.short()}" ,"its record holds no head seen here; it parted before this system first saw it")

  for m in in_use:
    attach_account(dirp__Account_Tree ,db ,m ,log ,preview)
  import Share   # here, as Share imports this module
  Share.share__apply(system_db ,db ,log ,preview)
  import Sound   # here, as Sound imports StoragePlug, which imports this module
  Sound.fifo__sync_storage(system_db ,db ,log ,preview)
  for name ,list__share in dict__share_skipped.items():
    for share in list__share:
      if not Share.is__member(name ,share) and not preview:
        log.line("warning" ,name ,f"was a member of the group {share} here, a share the storage database does not record,"
                 " so it is not made again; Account-Tree share makes it, and share record keeps such shares before an unplug")
  mapped = {m["database_uid"] for m in in_use}
  for a in db.rows("SELECT * FROM account WHERE state = 'active' ORDER BY name"):
    if a["database_uid"] not in mapped:
      log.line("skipped" ,f"storage account {a['name']}" ,"not the same account as any system account here")
  SameAccount.system_seen__record(db ,system_db.uuid() ,log ,preview)
  seen_series = SameAccount.head_seen__record(system_db ,db ,"attached" ,kind ,preview)
  log.line("recorded" ,f"database {db.short()} attached" ,f"head at series {seen_series} remembered here")

def attach_account(dirp__Account_Tree ,db ,m ,log ,preview):
  a = db.row("SELECT * FROM account WHERE database_uid = ?" ,(m["database_uid"],))
  if a is not None and a["state"] == "deprecated":
    log.line("skipped" ,m["system_account__name"] ,"deprecated, so its home is not mounted; it is kept until deallocated"); return
  if a is None or a["state"] != "active":
    log.error(m["system_account__name"] ,f"the system map names database uid {m['database_uid']},"
              " which is not an active storage account of this database"); return
  dirpa__target ,entry = SameAccount.mount_target(m)
  if entry is None or entry.pw_name != m["system_account__name"]:
    log.error(m["system_account__name"] ,f"no system account {m['system_account__name']} with system uid {m['system_uid']};"
              " it is to be made again"); return
  if entry.pw_dir != str(dirpa__target):
    log.error(m["system_account__name"] ,f"its home is {entry.pw_dir}; Account-Tree mounts a home only at {dirpa__target}"); return
  dirp__source = Database.dirp__account_data(dirp__Account_Tree) / a["name"]
  if not dirp__source.is_dir():
    log.error(str(dirp__source) ,"no such directory"); return
  if Kernel.is__mount_point(dirpa__target):
    log.line("kept" ,str(dirpa__target) ,"already mounted"); return
  if dirpa__target.exists():
    if not dirpa__target.is_dir():
      log.error(str(dirpa__target) ,"exists and is not a directory"); return
    if any(dirpa__target.iterdir()):
      log.error(str(dirpa__target) ,"not empty and not a mount point; nothing is mounted over it"); return
  else:
    if not act(log ,preview ,str(dirpa__target) ,os.mkdir ,dirpa__target ,0o000): return
    if not act(log ,preview ,str(dirpa__target) ,os.chmod ,dirpa__target ,0o000): return
    if not act(log ,preview ,str(dirpa__target) ,Kernel.immutable__set ,dirpa__target ,True): return
    log.line("made" ,str(dirpa__target) ,"mount point, root, mode 0000, immutable")
  database_uid = m["database_uid"]
  if not act(log ,preview ,str(dirpa__target) ,Kernel.home__mount ,dirp__source ,dirpa__target ,database_uid ,m["system_uid"] ,m["system_gid"]):
    return
  how = ("bind mount, the database uid and system uid are the same" if database_uid == m["system_uid"] == m["system_gid"]
         else f"idmapped, database uid {database_uid} to system uid {m['system_uid']}")
  log.line("mounted" ,str(dirpa__target) ,f"{how}; nosuid, nodev")

def detach(dirp__storage ,log ,preview):
  system_db = open_system_database(log)
  if system_db is None: return
  db = open_storage_database(dirp__storage ,log)
  if db is None: return
  dirp__Account_Tree = dirpa__Account_Tree(dirp__storage)
  in_session = Kernel.set__session__system_uid()
  in_use = system_map__in_use(system_db ,db)
  failed = False
  for m in in_use:
    a = db.row("SELECT name FROM account WHERE database_uid = ?" ,(m["database_uid"],))
    dirpa__target ,_ = SameAccount.mount_target(m)
    dirp__source = Database.dirp__account_data(dirp__Account_Tree) / (a["name"] if a else "")
    if not SameAccount.is__mounted_from(dirpa__target ,dirp__source):
      log.line("kept" ,str(dirpa__target) ,"not mounted from this storage"); continue
    if m["system_uid"] in in_session:
      log.error(m["system_account__name"] ,"has a login session; not detached"); failed = True; continue
    if act(log ,preview ,str(dirpa__target) ,Kernel.home__unmount ,dirpa__target):
      log.line("unmounted" ,str(dirpa__target))
    else:
      failed = True
  if in_use and not failed:
    SameAccount.system_seen__record(db ,system_db.uuid() ,log ,preview)
    seen_series = SameAccount.head_seen__record(system_db ,db ,"detached" ,None ,preview)
    log.line("recorded" ,f"database {db.short()} detached" ,f"head at series {seen_series} remembered here")
