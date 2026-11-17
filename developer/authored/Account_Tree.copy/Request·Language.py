# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Request·Language - the language definition of Request, the instruction
language a person's Account-Tree program gives the request gate in.

Data only; see Man-In-Grey's Language.py for its form. Each instruction is a
request, named for the work it asks for, so the guard can check it against
who asked and what the account tree allows. A journal holds one request.

  enter(account_name ,display ,terminal_type ,>session)
                       start a login session of account_name, a child account
                       below the account that asked, on a new terminal, and
                       write the terminal to session. display names the
                       asking account's display, for the child to open
                       windows on; each of its texts is empty where there is
                       none. terminal_type is the TERM the session is given.
                       session holds the terminal's master side, a
                       descriptor, which the asking program relays its own
                       terminal to.
"""

NAME = "Request"

DEFINITION = {
  "list__type": [
    ["account_name" ,"text"]
    ,["display" ,["dictionary"
                  ,["display" ,"text"]            # DISPLAY, as :0, for X programs; empty for none
                  ,["wayland_display" ,"text"]    # the Wayland socket's absolute path; empty for none
                  ,["xauthority" ,"text"]]]       # the X authority file's absolute path; empty for none
    ,["terminal_type" ,"text"]
    ,["session" ,["dictionary" ,["pty" ,"descriptor"]]]
  ]
  ,"list__format": [
    ["format__enter" ,["in" ,"account_name"] ,["in" ,"display"] ,["in" ,"terminal_type"] ,["out" ,"session"]]
  ]
  ,"list__result": ["session"]
  ,"map__instruction": {
    "enter": "format__enter"
  }
}
