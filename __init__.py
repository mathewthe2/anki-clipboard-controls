import json
import os

from aqt import gui_hooks, mw
from aqt.editor import Editor
from aqt.qt import (
    QAction,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
)


# ============================================================
# Configuration
# ============================================================

CURRENT_CONFIG_VERSION = "0.1"

DEFAULT_SETTINGS = {
    "version": CURRENT_CONFIG_VERSION,
    "remove_spaces": False,
    "paste_as_plain_text": True,
}

CONFIG_FILENAME = "clipboard_settings.json"


def get_settings_path():
    """Return the path to our persistent settings file."""

    addon_name = mw.addonManager.addonFromModule(__name__)

    addon_folder = mw.addonManager.addonsFolder(
        addon_name
    )

    user_files_folder = os.path.join(
        addon_folder,
        "user_files",
    )

    os.makedirs(
        user_files_folder,
        exist_ok=True,
    )

    return os.path.join(
        user_files_folder,
        CONFIG_FILENAME,
    )


# ============================================================
# Load settings
# ============================================================

def load_settings():
    """
    Load settings from the persistent JSON file.

    Creates the file if it doesn't exist.
    """

    path = get_settings_path()

    # --------------------------------------------------------
    # Create default settings if the file doesn't exist.
    # --------------------------------------------------------

    if not os.path.exists(path):

        settings = DEFAULT_SETTINGS.copy()

        save_settings(settings)

        return settings

    # --------------------------------------------------------
    # Read existing settings.
    # --------------------------------------------------------

    try:

        with open(
            path,
            "r",
            encoding="utf-8",
        ) as file:

            settings = json.load(file)

    except Exception as error:

        print(
            "Clipboard Controls: "
            f"Could not read settings: {error}"
        )

        settings = DEFAULT_SETTINGS.copy()

        save_settings(settings)

        return settings

    # --------------------------------------------------------
    # Validate settings.
    # --------------------------------------------------------

    if not isinstance(settings, dict):

        settings = DEFAULT_SETTINGS.copy()

        save_settings(settings)

        return settings

    # --------------------------------------------------------
    # Make sure required settings exist.
    # --------------------------------------------------------

    changed = False

    if "version" not in settings:
        settings["version"] = CURRENT_CONFIG_VERSION
        changed = True

    if "remove_spaces" not in settings:
        settings["remove_spaces"] = False
        changed = True

    if "paste_as_plain_text" not in settings:
        settings["paste_as_plain_text"] = False
        changed = True

    if settings["version"] != CURRENT_CONFIG_VERSION:
        settings["version"] = CURRENT_CONFIG_VERSION
        changed = True

    if changed:
        save_settings(settings)

    return settings


# ============================================================
# Save settings
# ============================================================

def save_settings(settings):
    """Save settings to the persistent JSON file."""

    path = get_settings_path()

    settings["version"] = CURRENT_CONFIG_VERSION

    try:

        with open(
            path,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                settings,
                file,
                indent=4,
            )

    except Exception as error:

        print(
            "Clipboard Controls: "
            f"Could not save settings: {error}"
        )


# ============================================================
# Load configuration at startup
# ============================================================

settings = load_settings()

remove_spaces = bool(
    settings.get(
        "remove_spaces",
        False,
    )
)

paste_as_plain_text = bool(
    settings.get(
        "paste_as_plain_text",
        False,
    )
)


# ============================================================
# Editor tracking
# ============================================================

editors = []


# ============================================================
# JavaScript paste handler
# ============================================================

PASTE_HANDLER = r"""
(function() {

    // Remove an existing handler first.
    if (
        window.removeSpacesPasteInstalled &&
        window.removeSpacesPasteHandler
    ) {
        document.removeEventListener(
            "paste",
            window.removeSpacesPasteHandler,
            true
        );
    }


    window.removeSpacesPasteHandler = function(event) {

        const removeSpaces =
            window.removeSpacesPasteEnabled === true;

        const pasteAsPlainText =
            window.pasteAsPlainTextEnabled === true;


        // If both options are disabled, let Anki
        // perform its normal paste.
        if (
            !removeSpaces &&
            !pasteAsPlainText
        ) {
            return;
        }


        if (!event.clipboardData) {
            return;
        }


        // Always obtain the plain-text version.
        //
        // This removes HTML formatting such as:
        //
        // - fonts
        // - colors
        // - bold
        // - italic
        // - underline
        // - links
        // - tables
        // - images
        // - other HTML formatting
        //

        let text =
            event.clipboardData.getData("text/plain");


        if (
            text === null ||
            text === undefined
        ) {
            return;
        }


        // ----------------------------------------------------
        // Remove whitespace if enabled.
        // ----------------------------------------------------

        if (removeSpaces) {
            text = text.replace(/\s/g, "");
        }


        // ----------------------------------------------------
        // Stop Anki's normal rich-text paste.
        // ----------------------------------------------------

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();


        // ----------------------------------------------------
        // Insert plain text.
        // ----------------------------------------------------

        document.execCommand(
            "insertText",
            false,
            text
        );
    };


    // Install the paste handler.
    document.addEventListener(
        "paste",
        window.removeSpacesPasteHandler,
        true
    );


    window.removeSpacesPasteInstalled = true;

})();
"""


# ============================================================
# Editor handling
# ============================================================

def on_editor_init(editor: Editor):
    """Initialize a newly-created editor."""

    if editor not in editors:
        editors.append(editor)

    editor.web.eval(
        PASTE_HANDLER
    )

    update_editor(editor)


def update_editor(editor: Editor):
    """Update the JavaScript settings."""

    remove_spaces_value = (
        "true"
        if remove_spaces
        else "false"
    )

    plain_text_value = (
        "true"
        if paste_as_plain_text
        else "false"
    )

    editor.web.eval(
        "window.removeSpacesPasteEnabled = "
        f"{remove_spaces_value};"
    )

    editor.web.eval(
        "window.pasteAsPlainTextEnabled = "
        f"{plain_text_value};"
    )


gui_hooks.editor_did_init.append(
    on_editor_init
)


# ============================================================
# Settings dialog
# ============================================================

class ClipboardControls(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle(
            "Clipboard Controls"
        )

        self.setMinimumWidth(360)

        layout = QVBoxLayout()


        # ----------------------------------------------------
        # Remove spaces
        # ----------------------------------------------------

        self.remove_spaces_checkbox = QCheckBox(
            "Remove spaces"
        )

        current_settings = load_settings()

        self.remove_spaces_checkbox.setChecked(
            bool(
                current_settings.get(
                    "remove_spaces",
                    False,
                )
            )
        )

        layout.addWidget(
            self.remove_spaces_checkbox
        )


        # ----------------------------------------------------
        # Paste as plain text
        # ----------------------------------------------------

        self.plain_text_checkbox = QCheckBox(
            "Paste as plain text"
        )

        self.plain_text_checkbox.setChecked(
            bool(
                current_settings.get(
                    "paste_as_plain_text",
                    False,
                )
            )
        )

        layout.addWidget(
            self.plain_text_checkbox
        )


        # ----------------------------------------------------
        # Buttons
        # ----------------------------------------------------

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            |
            QDialogButtonBox.StandardButton.Cancel
        )

        buttons.accepted.connect(
            self.save
        )

        buttons.rejected.connect(
            self.reject
        )

        layout.addWidget(
            buttons
        )

        self.setLayout(
            layout
        )


    def save(self):
        global remove_spaces
        global paste_as_plain_text
        global settings


        # Read checkbox values.
        remove_spaces = (
            self.remove_spaces_checkbox.isChecked()
        )

        paste_as_plain_text = (
            self.plain_text_checkbox.isChecked()
        )


        # Update settings.
        settings["version"] = CURRENT_CONFIG_VERSION

        settings["remove_spaces"] = remove_spaces

        settings["paste_as_plain_text"] = (
            paste_as_plain_text
        )


        # Save settings.
        save_settings(
            settings
        )


        # Update currently-open editors.
        for editor in editors:

            try:
                update_editor(editor)

            except Exception:
                pass


        self.accept()


# ============================================================
# Open settings
# ============================================================

def open_clipboard_controls():

    dialog = ClipboardControls(
        mw
    )

    dialog.exec()


# ============================================================
# Anki menu
# ============================================================

action = QAction(
    "Clipboard Controls",
    mw
)

action.triggered.connect(
    open_clipboard_controls
)

mw.form.menuTools.addAction(
    action
)
