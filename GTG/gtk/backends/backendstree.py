# -----------------------------------------------------------------------------
# Getting Things GNOME! - a personal organizer for the GNOME desktop
# Copyright (c) 2008-2013 - Lionel Dricot & Bertrand Rousseau
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.
# -----------------------------------------------------------------------------

from gi.repository import Gtk

from GTG.gtk.colors import get_colored_tags_markup
from GTG.backends.backend_signals import BackendSignals

ALLTASKS_TAG = 'gtg-tags-all'

class BackendsTree(Gtk.TreeView):
    """
    Gtk.TreeView that shows the currently loaded backends.
    """

    COLUMN_BACKEND_ID = 0  # never shown, used for internal lookup.
    COLUMN_ICON = 1
    COLUMN_TEXT = 2  # holds the backend "human-readable" name
    COLUMN_TAGS = 3
    COLUMN_ENABLED = 4

    def __init__(self, backendsdialog):
        """
        Constructor, just initializes the gtk widgets

        @param backends: a reference to the dialog in which this is
        loaded
        """
        super().__init__()
        self.dialog = backendsdialog
        self.ds = backendsdialog.ds
        self._init_liststore()
        self._init_renderers()
        self._init_signals()
        self.refresh()

    def refresh(self):
        """refreshes the Gtk.Liststore"""
        self.backendid_to_iter = {}
        self.liststore.clear()

        # Sort backends
        # 1, put default backend on top
        # 2, sort backends by human name
        backends = list(self.ds.get_all_backends(disabled=True))
        backends = sorted(backends,
                          key=lambda backend: (not backend.is_default(),
                                               backend.get_human_name()))

        for backend in backends:
            self.add_backend(backend)
            self.on_backend_state_changed(None, backend.get_id())

    def on_backend_added(self, sender, backend_id):
        """
        Signal callback executed when a new backend is loaded

        @param sender: not used, only here to let this function be used as a
                       callback
        @param backend_id: the id of the backend to add
        """
        # Add
        backend = self.ds.get_backend(backend_id)
        if not backend:
            return
        self.add_backend(backend)
        self.refresh()
        # Select
        self.select_backend(backend_id)
        # Update it's enabled state
        self.on_backend_state_changed(None, backend.get_id())

    def add_backend(self, backend):
        """
        Adds a new backend to the list

        @param backend_id: the id of the backend to add
        """
        if backend:
            backend_iter = self.liststore.append([
                backend.get_id(),
                backend.get_icon(),
                backend.get_human_name(),
                self._get_markup_for_tags(backend.get_attached_tags()),
                backend.is_enabled()
            ])
            self.backendid_to_iter[backend.get_id()] = backend_iter

    def on_backend_state_changed(self, sender, backend_id):
        """
        Signal callback executed when a backend is enabled/disabled.

        @param sender: not used, only here to let this function be used as a
                       callback
        @param backend_id: the id of the backend to add
        """
        if backend_id in self.backendid_to_iter:
            b_iter = self.backendid_to_iter[backend_id]
            b_path = self.liststore.get_path(b_iter)
            backend = self.ds.get_backend(backend_id)
            backend_name = backend.get_human_name()
            self.liststore[b_path][self.COLUMN_TEXT] = backend_name
            self.liststore[b_path][self.COLUMN_ENABLED] = backend.is_enabled()

            # Also refresh the tags
            new_tags = self._get_markup_for_tags(backend.get_attached_tags())
            self.liststore[b_path][self.COLUMN_TAGS] = new_tags

    def _get_markup_for_tags(self, tag_names):
        """Given a list of tags names, generates the pango markup to render
         that list with the tag colors used in GTG

        @param tag_names: the list of the tags (strings)
        @return str: the pango markup string
        """
        if ALLTASKS_TAG in tag_names:
            tags_txt = ""
        else:
            tags_txt = get_colored_tags_markup(self.ds, tag_names)
        return "<small>" + tags_txt + "</small>"

    def remove_backend(self, backend_id):
        """ Removes a backend from the treeview, and selects the first (to show
        something in the configuration panel

        @param backend_id: the id of the backend to remove
        """
        if backend_id in self.backendid_to_iter:
            self.liststore.remove(self.backendid_to_iter[backend_id])
            del self.backendid_to_iter[backend_id]
            self.select_backend()

    def _init_liststore(self):
        """Creates the liststore"""
        self.liststore = Gtk.ListStore(object, str, str, str, bool)
        self.set_model(self.liststore)

    def _init_renderers(self):
        """Initializes the cell renderers"""
        # We hide the columns headers
        self.set_headers_visible(False)
        # For the backend icon
        pixbuf_cell = Gtk.CellRendererPixbuf()
        tvcolumn_pixbuf = Gtk.TreeViewColumn('Icon', pixbuf_cell)
        tvcolumn_pixbuf.add_attribute(pixbuf_cell, 'icon-name', self.COLUMN_ICON)
        self.append_column(tvcolumn_pixbuf)
        # For the backend name
        text_cell = Gtk.CellRendererText()
        tvcolumn_text = Gtk.TreeViewColumn('Name', text_cell)
        tvcolumn_text.add_attribute(text_cell, 'markup', self.COLUMN_TEXT)
        tvcolumn_text.add_attribute(text_cell, 'sensitive', self.COLUMN_ENABLED)
        self.append_column(tvcolumn_text)
        text_cell.connect('edited', self.cell_edited_callback)
        text_cell.set_property('editable', True)
        # For the backend tags
        tags_cell = Gtk.CellRendererText()
        tvcolumn_tags = Gtk.TreeViewColumn('Tags', tags_cell)
        tvcolumn_tags.add_attribute(tags_cell, 'markup', self.COLUMN_TAGS)
        self.append_column(tvcolumn_tags)

    def cell_edited_callback(self, text_cell, path, new_text):
        """If a backend name is changed, it saves the changes in the Backend

        @param text_cell: not used. The Gtk.CellRendererText that emitted the
                          signal. Only here because it's passed by the signal
        @param path: the Gtk.TreePath of the edited cell
        @param new_text: the new name of the backend
        """
        # we strip everything not permitted in backend names
        new_text = ''.join(c for c in new_text if (c.isalnum() or c in [" ", "-", "_"]))
        selected_iter = self.liststore.get_iter(path)
        # update the backend name
        backend_id = self.liststore.get_value(selected_iter,
                                              self.COLUMN_BACKEND_ID)
        backend = self.dialog.get_requester().get_backend(backend_id)
        if backend:
            backend.set_human_name(new_text)
            # update the text in the liststore
            self.liststore.set(selected_iter, self.COLUMN_TEXT, new_text)

    def _init_signals(self):
        """Initializes the backends and gtk signals """
        self.connect("cursor-changed", self.on_select_row)
        _signals = BackendSignals()
        _signals.connect(_signals.BACKEND_ADDED, self.on_backend_added)
        _signals.connect(_signals.BACKEND_STATE_TOGGLED,
                         self.on_backend_state_changed)

    def on_select_row(self, treeview=None):
        """When a row is selected, displays the corresponding editing panel

        @var treeview: not used
        """
        self.dialog.on_backend_selected(self.get_selected_backend_id())

    def _get_selected_path(self):
        """
        Helper function to get the selected path

        @return Gtk.TreePath : returns exactly one path for the selected object
                               or None
        """
        selection = self.get_selection()
        if selection:
            model, selected_paths = self.get_selection().get_selected_rows()
            if selected_paths:
                return selected_paths[0]
        return None

    def select_backend(self, backend_id=None):
        """
        Selects the backend corresponding to backend_id.
        If backend_id is none, refreshes the current configuration panel.

        @param backend_id: the id of the backend to select
        """
        selection = self.get_selection()
        if backend_id in self.backendid_to_iter:
            backend_iter = self.backendid_to_iter[backend_id]
            if selection:
                selection.select_iter(backend_iter)
        else:
            if self._get_selected_path():
                # We just reselect the currently selected entry
                self.on_select_row()
            else:
                # If nothing is selected, we select the first entry
                if selection:
                    selection.select_path("0")
        self.dialog.on_backend_selected(self.get_selected_backend_id())

    def get_selected_backend_id(self):
        """
        returns the selected backend id, or none

        @return string: the selected backend id (or None)
        """
        selected_path = self._get_selected_path()
        if not selected_path:
            return None
        selected_iter = self.liststore.get_iter(selected_path)
        return self.liststore.get_value(selected_iter, self.COLUMN_BACKEND_ID)
