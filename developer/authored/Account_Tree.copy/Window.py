# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Window - the Account-Tree resource window

One window shows the resources of one account, the window account, runs
under it, and acts with its authority. So a window means the same thing
however many are open on one desktop: what it offers is what its account can
do. Clicking a child account asks the request gate to open that account's
window, which the gate starts as a session of the child account, on this
window's display, as enter starts a shell; it is the window the child would
get from a shell of its own.

The window is made of panels, each a framed area, so that every option is
visible at once without menus. An option that has no implementation yet is
shown greyed out. Pointing at any option shows what it does in a tooltip.

  Account        the window account, its place in the tree, and its home
  Share          the accounts the window account is shared with on this
                 system, sharing with another, and ending a share
  Request        what each request did, as the request interpreter reported
                 it, or why it was refused
  Child account  the child accounts, each with its window, enter and
                 deallocate, and making one: what an account does to another
                 is done from above, in the parent's window
  Allocate       the kinds of resource, by group
  Sound          the tree's buses, the permits of the window account and its
                 child accounts, and the window account's connection table;
                 see developer/design_audio.html

Every change is a request to the request gate, made through the work
functions of Request·Composer.py, the same ones the commands call; the
guard decides. The window reads the tree from the names of the system
accounts, AccountTree.py, and the sound of an account with the request
sound_show. A request blocks the window for the moment it takes.

The window is drawn with GTK 4, the toolkit of the desktop's own programs,
so it opens on Wayland directly, or on X when that is what the session has.
"""

import os ,shutil ,subprocess

import AccountTree
import ResourceKind
import Share

GTK__MISSING = """\
Account-Tree window: GTK 4 for Python is not available to {python}
  {error}
This Python needs the PyGObject package and the GTK 4 introspection data.
  System Python, openSUSE:  zypper install python313-gobject typelib-1_0-Gtk-4_0   (313 for Python 3.13)
  Project Python:           zypper install gobject-introspection-devel cairo-devel typelib-1_0-Gtk-4_0
                            python3 -m pip install PyGObject
"""

APPLICATION_ID = "com.ReasoningTechnology.Account-Tree"
PAD = 6
STATE_REFRESH__SECONDS = 5
FPA__ACCOUNT_TREE = os.path.join(os.path.dirname(os.path.realpath(__file__)) ,"Account-Tree")

# run in the terminal that enter opens: $1 is Account-Tree, $2 the account
ENTER__SCRIPT = '"$1" enter "$2" || { echo; echo "Press Enter to close this terminal."; read line; }'

MARK__SYMBOL = {"blank": "blank" ,"gray": "held, not in force" ,"full": "held and in force"}


def load_gtk():
  # Draw with cairo, on the processor, and do not open OpenGL at all. A
  # window of buttons gains nothing from the graphics chip, and a child account
  # is often not allowed to open it, which makes GTK print a warning for every
  # attempt. GDK_DISABLE=gl is read by GTK 4.16 and later. Values already in
  # the environment win.
  os.environ.setdefault("GSK_RENDERER" ,"cairo")
  os.environ.setdefault("GDK_DISABLE" ,"gl")
  import gi
  gi.require_version("Gtk" ,"4.0")
  from gi.repository import Gtk ,Gio ,GLib
  return Gtk ,Gio ,GLib


# Panel borders drawn in the theme's own text colour at partial strength, so
# they stand out on a dark theme and a light one alike. The theme's default
# frame border is faint on dark themes.
PANEL__CSS = """
frame.account-tree-panel > border {
  border: 1px solid alpha(currentColor ,0.45);
  border-radius: 6px;
}
frame.account-tree-panel > label {
  font-weight: bold;
}
textview.account-tree-text {
  font-family: monospace;
}
"""

def install_css(Gtk):
  from gi.repository import Gdk
  provider = Gtk.CssProvider()
  if hasattr(provider ,"load_from_string"):
    provider.load_from_string(PANEL__CSS)
  else:
    provider.load_from_data(PANEL__CSS ,-1)
  Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default() ,provider,
    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def terminal__argv(argv):
  """
  The command that opens a terminal running argv: GNOME Console, kgx, which
  IdealX has, then gnome-terminal, then xterm. None when there is none.
  """
  if shutil.which("kgx"):
    return ["kgx" ,"--"] + argv
  if shutil.which("gnome-terminal"):
    return ["gnome-terminal" ,"--"] + argv
  if shutil.which("xterm"):
    return ["xterm" ,"-e"] + argv
  return None


def build_window_class(Gtk ,GLib):
  import Request·Composer as composer

  def box__clear(box):
    child = box.get_first_child()
    while child is not None:
      following = child.get_next_sibling()
      box.remove(child)
      child = following

  class PanelHelper:
    """
    The pieces both kinds of window are built from.
    """

    def panel(self ,title):
      """
      A framed panel and the box its contents go in.
      """
      frame = Gtk.Frame(label=title)
      frame.add_css_class("account-tree-panel")
      box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL ,spacing=PAD,
        margin_top=PAD ,margin_bottom=PAD ,margin_start=PAD ,margin_end=PAD)
      frame.set_child(box)
      return frame ,box

    def label(self ,text ,dim=False ,markup=False ,wrap=True):
      widget = Gtk.Label(xalign=0 ,wrap=wrap)
      if markup:
        widget.set_markup(text)
      else:
        widget.set_text(text)
      if dim:
        widget.add_css_class("dim-label")
      return widget

    def option(self ,text ,description ,action=None ,reason="not written yet"):
      """
      A clickable option. Without an action it is greyed out, and its
      tooltip says why: reason, by default that it is not written yet.
      """
      button = Gtk.Button(label=text)
      if action is None:
        button.set_sensitive(False)
        button.set_tooltip_text(f"{description}\n[{reason}]")
      else:
        button.set_tooltip_text(description)
        button.connect("clicked" ,lambda b: action())
      return button

    def row(self ,list__widget ,is__expand=True):
      box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL ,spacing=PAD)
      for widget in list__widget:
        if is__expand: widget.set_hexpand(True)
        box.append(widget)
      return box

    def entry(self ,placeholder ,tooltip):
      widget = Gtk.Entry(placeholder_text=placeholder)
      widget.set_tooltip_text(tooltip)
      widget.set_hexpand(True)
      return widget


  class AllocateWindow(PanelHelper ,Gtk.Window):
    """
    The window for allocating resources of one group, such as Storage, to
    the window account. Each kind of resource in the group is a row: its
    button, which does that kind's allocation in the resource window it
    was opened from, and what it is.
    """

    def __init__(self ,parent ,group ,window_account):
      super().__init__(transient_for=parent)
      self.window_account = window_account
      title = ResourceKind.GROUP_TITLE[group]
      self.set_title(f"Account-Tree: {window_account.name}: allocate {title}")

      box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL ,spacing=PAD,
        margin_top=PAD ,margin_bottom=PAD ,margin_start=PAD ,margin_end=PAD)
      box.append(self.label(f"<b>{escape(window_account.name)}</b>" ,markup=True))

      frame ,panel = self.panel(f"Allocate {title}")
      grid = Gtk.Grid(column_spacing=PAD*2 ,row_spacing=PAD)
      list__kind = dict(ResourceKind.list__kind__by_group())[group]
      for i ,kind in enumerate(list__kind):
        action = None
        if kind.implemented:
          def action(k=kind):
            self.close()
            getattr(parent ,k.action)()
        grid.attach(self.option(kind.name ,kind.description ,action) ,0 ,i ,1 ,1)
        text = kind.description if kind.implemented else f"{kind.description}  (not written yet)"
        description = self.label(text ,dim=not kind.implemented)
        description.set_hexpand(True)
        grid.attach(description ,1 ,i ,1 ,1)
      panel.append(grid)
      box.append(frame)

      close = Gtk.Button(label="Close" ,halign=Gtk.Align.END)
      close.connect("clicked" ,lambda b: self.close())
      box.append(close)
      self.set_child(box)
      self.set_default_size(560 ,-1)


  class AskWindow(PanelHelper ,Gtk.Window):
    """
    A small window asking for one line of text: its question, an entry, and a
    button that acts on what was typed. With confirm, the button is offered
    only once the entry holds exactly that text, as for deallocation, where
    the account's full name is typed.
    """

    def __init__(self ,parent ,title ,question ,verb ,action ,confirm=None ,placeholder=""):
      super().__init__(transient_for=parent ,modal=True)
      self.set_title(f"Account-Tree: {title}")
      box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL ,spacing=PAD,
        margin_top=PAD*2 ,margin_bottom=PAD*2 ,margin_start=PAD*2 ,margin_end=PAD*2)
      box.append(self.label(question))
      self.text = Gtk.Entry(placeholder_text=placeholder)
      box.append(self.text)
      cancel = Gtk.Button(label="Cancel")
      cancel.connect("clicked" ,lambda b: self.close())
      self.do = Gtk.Button(label=verb)
      self.do.add_css_class("destructive-action" if confirm else "suggested-action")
      def act(*_):
        if not self.do.get_sensitive(): return
        value = self.text.get_text().strip()
        self.close()
        action(value)
      self.do.connect("clicked" ,act)
      self.text.connect("activate" ,act)
      if confirm is not None:
        self.do.set_sensitive(False)
        self.text.connect("changed" ,lambda e: self.do.set_sensitive(e.get_text().strip() == confirm))
      line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL ,spacing=PAD ,halign=Gtk.Align.END)
      line.append(cancel); line.append(self.do)
      box.append(line)
      self.set_child(box)
      self.set_default_size(420 ,-1)


  class ResourceWindow(PanelHelper ,Gtk.ApplicationWindow):

    def __init__(self ,application ,window_account):
      super().__init__(application=application)
      self.window_account = window_account
      self.set_title(f"Account-Tree: {window_account.name}")

      grid = Gtk.Grid(column_spacing=PAD ,row_spacing=PAD,
        margin_top=PAD ,margin_bottom=PAD ,margin_start=PAD ,margin_end=PAD)
      grid.set_column_homogeneous(True)
      #   row 0   Account                  Share   Request
      #   row 1   Child account, across two         Allocate
      #   row 2   Sound, across the three
      grid.attach(self.panel__identity() ,0 ,0 ,1 ,1)
      grid.attach(self.panel__share() ,1 ,0 ,1 ,1)
      grid.attach(self.panel__request() ,2 ,0 ,1 ,1)
      grid.attach(self.panel__child_account() ,0 ,1 ,2 ,1)
      grid.attach(self.panel__allocate() ,2 ,1 ,1 ,1)
      grid.attach(self.panel__sound() ,0 ,2 ,3 ,1)

      # The panels can be taller than the screen allows a window to be. In a
      # scrolled window they keep their natural size and the window can be
      # any size, instead of GTK warning that the window is too short.
      scroller = Gtk.ScrolledWindow(propagate_natural_height=True ,propagate_natural_width=True)
      scroller.set_child(grid)
      self.set_child(scroller)
      GLib.timeout_add_seconds(STATE_REFRESH__SECONDS ,self.refresh_child_state)

    # ----------------------------------------------------------------------------
    # requests

    def request(self ,what ,function ,*argument):
      """
      Make a request through Request·Composer and report it in the Request
      panel: what the interpreter did, or why the request was refused.
      Returns what the work function returns, or None when it was refused.
      """
      try:
        value = function(*argument)
      except composer.RequestError as error:
        list__line = [line.strip() for line in (error.output or "").splitlines()
                      if any(word in line for word in ("broken" ,"refused" ,"error" ,"failed"))]
        self.report(what ,[f"not done: {error}"] + list__line)
        return None
      output = value[1] if isinstance(value ,tuple) else value
      if isinstance(output ,str):
        self.report(what ,composer.list__done(output) or ["done"])
      return value

    def report(self ,what ,list__line):
      buffer = self.request__text.get_buffer()
      text = what + "\n" + "".join(f"  {line}\n" for line in list__line)
      buffer.insert(buffer.get_end_iter() ,text)
      GLib.idle_add(lambda: self.request__text.scroll_to_mark(buffer.get_insert() ,0 ,False ,0 ,0) and False)

    # ----------------------------------------------------------------------------
    # panels

    def panel__identity(self):
      frame ,box = self.panel("Account")
      name = self.window_account.name
      parent = AccountTree.parent_of(name)
      box.append(self.label(f"<big><b>{escape(name)}</b></big>" ,markup=True))
      if not parent:
        relation = "root, at the top of the account tree"
      elif parent == "root":
        relation = "login account, a child of root"
      else:
        relation = f"child account of {parent}"
      box.append(self.label(f"system uid {self.window_account.uid}   {relation}"))
      state = "present" if self.window_account.home_exists else "not found"
      box.append(self.label(f"home   {self.window_account.home}   ({state})"))
      return frame

    def panel__request(self):
      frame ,box = self.panel("Request")
      self.request__text = Gtk.TextView(editable=False ,cursor_visible=False ,wrap_mode=Gtk.WrapMode.WORD_CHAR)
      self.request__text.add_css_class("account-tree-text")
      scroller = Gtk.ScrolledWindow(min_content_height=110 ,vexpand=True)
      scroller.set_child(self.request__text)
      box.append(scroller)
      box.append(self.label(f"each change is a request of {self.window_account.name}; the request guard decides" ,dim=True))
      return frame

    def panel__child_account(self):
      """
      One row per child account of the window account: a button with its
      short name, which opens its window, and its state; and making one. The
      states are read again every few seconds, so a session starting or
      ending shows without reopening the window.
      """
      self.child__frame ,self.child__box = self.panel("Child account")
      self.child__fill()
      return self.child__frame

    def child__fill(self):
      box = self.child__box
      box__clear(box)
      self.child_state__label = []
      list__child = AccountTree.list__child_account(self.window_account.name)
      if not list__child:
        box.append(self.label("(none)" ,dim=True))
      else:
        grid = Gtk.Grid(column_spacing=PAD*2 ,row_spacing=PAD)
        set__session = AccountTree.set__session__system_uid()
        for i ,child in enumerate(list__child):
          button = Gtk.Button(label=AccountTree.short_name(child.name))
          button.get_child().set_xalign(0)
          button.set_hexpand(True)
          button.set_tooltip_text(f"open the resource window of {child.name}; it runs under {child.name}, with its authority")
          button.connect("clicked" ,lambda b ,c=child: self.open_child_account(c))
          grid.attach(button ,0 ,i ,1 ,1)
          state = self.label(AccountTree.state(child ,set__session))
          grid.attach(state ,1 ,i ,1 ,1)
          self.child_state__label.append((child ,state))
          grid.attach(self.option("enter" ,f"open a terminal with a login shell of {child.name}"
                                  ,lambda c=child: self.enter(c)) ,2 ,i ,1 ,1)
          grid.attach(self.option("deallocate"
            ,f"remove {child.name}: its processes end, its system account goes, its home is moved to account-deallocated on its storage"
            ,lambda c=child: self.deallocate(c)) ,3 ,i ,1 ,1)
        box.append(grid)
      box.append(self.option("make child account" ,f"make an account below {self.window_account.name}"
                             ,self.child_account__make))

    def refresh_child_state(self):
      list__name = [child.name for child in AccountTree.list__child_account(self.window_account.name)]
      if list__name != [child.name for child ,_ in self.child_state__label]:
        self.child__fill()             # made or deallocated from elsewhere
        return self.get_visible()
      set__session = AccountTree.set__session__system_uid()
      for child ,label in self.child_state__label:
        label.set_text(AccountTree.state(child ,set__session))
      return self.get_visible()       # False stops the timer once the window is closed

    def panel__share(self):
      """
      The accounts the window account is shared with on this system, each
      with a button ending the share, and sharing with another. A share
      makes the member a member of the window account's own group.
      """
      self.share__frame ,self.share__box = self.panel("Share")
      self.share__fill()
      return self.share__frame

    def share__fill(self):
      box = self.share__box
      box__clear(box)
      name = self.window_account.name
      list__member = Share.list__member(name)
      box.append(self.label(f"{AccountTree.short_name(name)} is shared with" ,dim=True))
      if not list__member:
        box.append(self.label("(no account)" ,dim=True))
      for member in list__member:
        end = Gtk.Button(label="end")
        end.set_tooltip_text(f"end the share of {name} with {member}")
        end.connect("clicked" ,lambda b ,m=member: self.share__remove(m))
        box.append(self.row([self.label(member) ,end] ,is__expand=False))
      entry = self.entry("account" ,"an account name, relative to the current account, or absolute with a leading ·")
      button = Gtk.Button(label="share with")
      button.set_tooltip_text(f"make the account typed a member of {name}'s own group")
      def share(*_):
        self.share__with(entry.get_text().strip())
      button.connect("clicked" ,share)
      entry.connect("activate" ,share)
      box.append(self.row([entry ,button] ,is__expand=False))

    def panel__allocate(self):
      """
      One button per group of resources. Each opens the window for
      allocating resources of that group.
      """
      frame ,box = self.panel("Allocate")
      for group ,list__kind in ResourceKind.list__kind__by_group():
        button = Gtk.Button(label=ResourceKind.GROUP_TITLE[group])
        button.set_tooltip_text(", ".join(kind.name for kind in list__kind))
        button.connect("clicked" ,lambda b ,g=group: self.open_allocate(g))
        box.append(button)
      return frame

    def panel__sound(self):
      self.sound__frame ,self.sound__box = self.panel("Sound")
      self.sound__fill()
      return self.sound__frame

    # ----------------------------------------------------------------------------
    # sound

    def sound__fill(self):
      """
      Fill the Sound panel from sound_show: the grant, the buses, the permit
      marks of the window account and its child accounts, and the window
      account's connection table. The window account's own marks decide
      which permits it can issue and revoke for its child accounts.
      """
      box = self.sound__box
      box__clear(box)
      name = self.window_account.name
      try:
        sound = composer.sound_show(name)
      except composer.RequestError as error:
        box.append(self.label(f"no sound to show: {error}" ,dim=True))
        list__line = [line.strip() for line in (error.output or "").splitlines() if "broken" in line]
        for line in list__line: box.append(self.label(line ,dim=True))
        refresh = Gtk.Button(label="read again" ,halign=Gtk.Align.START)
        refresh.connect("clicked" ,lambda b: self.sound__fill())
        box.append(refresh)
        return
      self.sound = sound
      is__login = name == sound["login"]
      if sound["has__grant"]:
        box.append(self.label(f"grant   held: {sound['login']}, the login account of the tree, holds this system's grant of sound"))
      else:
        box.append(self.label(f"grant   none: {sound['login']} holds no grant of sound from this system, so no permit in the tree is in force;"
                              f" the administrator issues one with Account-Tree_admin sound grant issue {sound['login']}"))
      if not sound["is__configured"]:
        box.append(self.label("sound is not configured for the tree yet: issuing its first permit makes the default buses" ,dim=True))
      grid = Gtk.Grid(column_spacing=PAD*2 ,row_spacing=PAD)
      frame ,inner = self.panel("Bus")
      inner.append(self.sound__bus(sound ,is__login))
      grid.attach(frame ,0 ,0 ,1 ,1)
      frame ,inner = self.panel("Permit")
      inner.append(self.sound__permit(sound ,is__login))
      grid.attach(frame ,1 ,0 ,1 ,1)
      frame ,inner = self.panel("Connection")
      self.sound__connection(sound ,inner)
      grid.attach(frame ,0 ,1 ,2 ,1)
      box.append(grid)
      refresh = Gtk.Button(label="read again" ,halign=Gtk.Align.START)
      refresh.set_tooltip_text("read the sound of this account again")
      refresh.connect("clicked" ,lambda b: self.sound__fill())
      box.append(refresh)
      # the panel is rebuilt; the focus would otherwise land on its first
      # entry, a bus name, with its text selected
      GLib.idle_add(lambda: self.set_focus(None) and False)

    def sound__bus(self ,sound ,is__login):
      grid = Gtk.Grid(column_spacing=PAD*2 ,row_spacing=PAD)
      for column ,heading in enumerate(("bus" ,"name" ,"gather permit" ,"broadcast permit")):
        grid.attach(self.label(f"<b>{heading}</b>" ,markup=True) ,column ,0 ,1 ,1)
      for i ,bus in enumerate(sound["list__bus"] ,1):
        grid.attach(self.label(str(bus["number"])) ,0 ,i ,1 ,1)
        if is__login:
          entry = Gtk.Entry(text=bus["name"])
          entry.set_tooltip_text("rename the bus: type its new name and press Enter")
          entry.connect("activate" ,lambda e ,n=bus["number"]: self.sound__bus_set(n ,e.get_text().strip()))
          grid.attach(entry ,1 ,i ,1 ,1)
        else:
          grid.attach(self.label(bus["name"]) ,1 ,i ,1 ,1)
        grid.attach(self.label(", ".join(bus["list__gather"]) or "-") ,2 ,i ,1 ,1)
        grid.attach(self.label(", ".join(bus["list__broadcast"]) or "-") ,3 ,i ,1 ,1)
        if is__login:
          remove = Gtk.Button(label="remove")
          remove.set_tooltip_text("remove the bus, with the permits for its ends; refused while a connection table names it")
          remove.connect("clicked" ,lambda b ,n=bus["number"]: self.sound__bus_remove(n))
          grid.attach(remove ,4 ,i ,1 ,1)
      row = len(sound["list__bus"]) + 1
      grid.attach(self.label("<b>device</b>" ,markup=True) ,0 ,row ,2 ,1)
      grid.attach(self.label("<b>permit</b>" ,markup=True) ,2 ,row ,2 ,1)
      row += 1
      for i ,device in enumerate(sound["list__device"]):
        grid.attach(self.label(device["device"]) ,0 ,row + i ,2 ,1)
        grid.attach(self.label(", ".join(device["list__holder"]) or "-") ,2 ,row + i ,2 ,1)
      if is__login:
        row += len(sound["list__device"])
        number = Gtk.Entry(placeholder_text="number" ,width_chars=6)
        name = Gtk.Entry(placeholder_text="name")
        make = Gtk.Button(label="make bus")
        make.set_tooltip_text("make a bus with this number and name; the login account holds the permits for its ends")
        def bus_make(*_):
          text = number.get_text().strip()
          if not text.isdigit():
            self.report("make bus" ,["not done: a bus number is a number"]); return
          self.sound__bus_set(int(text) ,name.get_text().strip())
        make.connect("clicked" ,bus_make)
        name.connect("activate" ,bus_make)
        grid.attach(number ,0 ,row ,1 ,1)
        grid.attach(name ,1 ,row ,1 ,1)
        grid.attach(make ,2 ,row ,1 ,1)
      return grid

    def sound__permit(self ,sound ,is__login):
      """
      A row for the window account and one for each child account, a column
      for each permit, each holding a mark: unchecked, blank, the permit not
      held; a dash, gray, held and not in force; checked, full, held and in
      force. Clicking a blank mark issues the permit, clicking another
      revokes it. A mark the window account cannot change is greyed out. The
      login account changes every mark of its tree, its own included; another
      account changes the marks of its child accounts, for the permits it
      holds, and none of its own: an account's permits come from above.
      """
      map__bus = {bus["number"]: bus["name"] for bus in sound["list__bus"]}
      list__permit = [m["permit"] for m in sound["list__row"][0]["list__mark"]]
      mark__own = {m["permit"]: m["mark"] for m in sound["list__row"][0]["list__mark"]}
      grid = Gtk.Grid(column_spacing=PAD ,row_spacing=PAD)
      grid.attach(self.label("<b>account</b>" ,markup=True) ,0 ,0 ,1 ,1)
      for column ,permit in enumerate(list__permit ,1):
        if permit.startswith("@"):
          heading ,tooltip = permit ,f"the permit for the device {permit}"
        else:
          number ,_ ,end = permit.partition(".")
          heading = f"{number} {end}"
          tooltip = f"the permit for the {end} end of bus {number}, {map__bus.get(int(number) ,'')}"
        title = self.label(f"<b>{escape(heading)}</b>" ,markup=True)
        title.set_tooltip_text(tooltip)
        grid.attach(title ,column ,0 ,1 ,1)
      for i ,row in enumerate(sound["list__row"] ,1):
        grid.attach(self.label(AccountTree.short_name(row["name"]) if i > 1 else row["name"]) ,0 ,i ,1 ,1)
        is__child_row = i > 1
        for column ,mark in enumerate(row["list__mark"] ,1):
          check = Gtk.CheckButton(halign=Gtk.Align.CENTER)
          check.set_active(mark["mark"] == "full")
          check.set_inconsistent(mark["mark"] == "gray")
          is__able = is__login or (is__child_row and mark__own.get(mark["permit"] ,"blank") != "blank")
          check.set_sensitive(is__able)
          verb = "issue" if mark["mark"] == "blank" else "revoke"
          check.set_tooltip_text(f"{row['name']}  {mark['permit']}: {MARK__SYMBOL[mark['mark']]}"
                                 + (f"; click to {verb} it" if is__able else ""))
          check.connect("toggled" ,lambda c ,r=row["name"] ,m=mark: self.sound__permit_toggle(r ,m))
          grid.attach(check ,column ,i ,1 ,1)
      return grid

    def sound__connection(self ,sound ,box):
      name = self.window_account.name
      if not sound["has__table"]:
        box.append(self.label(f"{name} has no connection table; it is made when its first permit is issued" ,dim=True))
        return
      box.append(self.label("one line to a connection:  gather|broadcast  <bus>  <endpoint>; the bus a number or a name,"
                            " in double quotes when it has a space; the endpoint @output, @input, or a regular expression"
                            " matched against a program's name. A line beginning with # is a comment." ,dim=True))
      text = Gtk.TextView(wrap_mode=Gtk.WrapMode.NONE ,monospace=True)
      text.add_css_class("account-tree-text")
      text.get_buffer().set_text(sound["connection"])
      scroller = Gtk.ScrolledWindow(min_content_height=120 ,hexpand=True)
      scroller.set_child(text)
      box.append(scroller)
      save = Gtk.Button(label="save")
      save.set_tooltip_text(f"replace the connection table of {name} with this text")
      def do_save(*_):
        buffer = text.get_buffer()
        self.sound__connection_set(buffer.get_text(buffer.get_start_iter() ,buffer.get_end_iter() ,False))
      save.connect("clicked" ,do_save)
      reset = Gtk.Button(label="reset to default")
      reset.set_tooltip_text(f"put back the default connection table of {name}")
      reset.connect("clicked" ,lambda b: self.sound__connection_set(None))
      box.append(self.row([save ,reset] ,is__expand=False))

    def sound__permit_toggle(self ,account_name ,mark):
      is__issue = mark["mark"] == "blank"
      what = f"{'issue' if is__issue else 'revoke'} the permit {mark['permit']} of {account_name}"
      self.request(what ,composer.sound_permit_issue ,account_name ,mark["permit"] ,is__issue)
      GLib.idle_add(lambda: self.sound__fill() and False)

    def sound__connection_set(self ,text):
      name = self.window_account.name
      what = f"{'reset' if text is None else 'set'} the connection table of {name}"
      # a refused table stays in the panel as typed, to be corrected
      if self.request(what ,composer.sound_connection_set ,name ,text) is not None:
        self.sound__fill()

    def sound__bus_set(self ,number ,name):
      self.request(f"set bus {number}, named {name}" ,composer.sound_bus_set ,number ,name)
      self.sound__fill()

    def sound__bus_remove(self ,number):
      self.request(f"remove bus {number}" ,composer.sound_bus_remove ,number)
      self.sound__fill()

    def sound__focus(self):
      """
      Show the Sound panel, as the Allocate window's sound kind asks: the
      focus moves to its first control, and the window scrolls to it.
      """
      self.present()
      self.sound__box.child_focus(Gtk.DirectionType.TAB_FORWARD)

    # ----------------------------------------------------------------------------
    # actions

    def name__expand(self ,text):
      "an account name typed into the window, expanded as the commands expand it; None, reported, when it cannot be"
      try:
        return AccountTree.account_name__expand(self.window_account.name ,text)
      except ValueError as error:
        self.report(f"the account name {text!r}" ,[f"not done: {error}"])
        return None

    def enter(self ,child):
      name = child.name
      # When entering fails, the terminal is held open on the error until
      # Enter is pressed, rather than closing before it can be read.
      argv = terminal__argv(["/bin/sh" ,"-c" ,ENTER__SCRIPT ,"Account-Tree"
                             ,FPA__ACCOUNT_TREE ,AccountTree.account_name__specifier(name)])
      if argv is None:
        self.report(f"enter {name}" ,["not done: no terminal program found; kgx, gnome-terminal or xterm is needed"])
        return
      try:
        subprocess.Popen(argv ,stdin=subprocess.DEVNULL ,start_new_session=True)
      except OSError as error:
        self.report(f"enter {name}" ,[f"not done: {argv[0]}: {error.strerror}"]); return
      self.report(f"enter {name}" ,[f"opened {argv[0]} running Account-Tree enter"])

    def deallocate(self ,child):
      name = child.name
      def do(_):
        if self.request(f"deallocate {name}" ,composer.deallocate ,name) is not None:
          self.child__fill()
          self.sound__fill()
      AskWindow(self ,f"deallocate {name}"
        ,f"Deallocating {name} ends its processes, deletes its system account, and moves its home to "
         "account-deallocated on its storage, for the administrator to remove. Type its full name to deallocate it."
        ,"deallocate" ,do ,confirm=name ,placeholder=name).present()

    def child_account__make(self):
      parent = self.window_account.name
      def do(text):
        if not text: return
        if AccountTree.SEPARATOR in text:
          self.report(f"make a child account of {parent}" ,["not done: give the child's own name, without the middle dot"]); return
        name = parent + AccountTree.SEPARATOR + text
        if self.request(f"make {name}" ,composer.make_child_account ,name) is not None:
          self.child__fill()
          self.sound__fill()
      AskWindow(self ,f"make a child account of {parent}"
        ,f"The new account's own name; it is made as {parent}·<name>." ,"make" ,do ,placeholder="name").present()

    def share__with(self ,text):
      member = self.name__expand(text) if text else None
      if member is None: return
      name = self.window_account.name
      self.request(f"share {name} with {member}" ,composer.share_with ,name ,[member])
      self.share__fill()

    def share__remove(self ,member):
      name = self.window_account.name
      self.request(f"end the share of {name} with {member}" ,composer.share_remove ,name ,[member])
      self.share__fill()

    def open_allocate(self ,group):
      AllocateWindow(self ,group ,self.window_account).present()

    def open_child_account(self ,child):
      "ask the request gate to start the child's window under the child"
      self.request(f"open the window of {child.name}" ,composer.window_open ,child.name)

  return ResourceWindow


def escape(text):
  return text.replace("&" ,"&amp;").replace("<" ,"&lt;").replace(">" ,"&gt;")


def run(window_account):
  """
  Draw the window of window_account, the account this program runs under; the
  window acts with its authority.
  """
  import sys
  try:
    Gtk ,Gio ,GLib = load_gtk()
  except (ImportError ,ValueError) as error:
    print(GTK__MISSING.format(python=sys.executable ,error=error) ,file=sys.stderr ,end="")
    return 1

  ResourceWindow = build_window_class(Gtk ,GLib)
  install_css(Gtk)
  application = Gtk.Application(application_id=APPLICATION_ID,
    flags=Gio.ApplicationFlags.NON_UNIQUE)
  application.connect("activate",
    lambda app: ResourceWindow(app ,window_account).present())
  return application.run([])
