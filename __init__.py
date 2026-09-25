import json
import os
import re
import urllib.request
import urllib.error

from aqt import gui_hooks, mw
from aqt.editor import Editor
from aqt.qt import (
    QAction,
    QByteArray,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QMimeData,
    QVBoxLayout,
)


# ============================================================
# Configuration
# ============================================================

CURRENT_CONFIG_VERSION = "0.1"

DEFAULT_SETTINGS = {
    "version": CURRENT_CONFIG_VERSION,
    "remove_spaces": False,
    "paste_as_plain_text": False,
    "paste_media_links": True,
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

    if not os.path.exists(path):

        settings = DEFAULT_SETTINGS.copy()

        save_settings(settings)

        return settings

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

    if not isinstance(settings, dict):

        settings = DEFAULT_SETTINGS.copy()

        save_settings(settings)

        return settings

    changed = False

    if "version" not in settings:
        settings["version"] = CURRENT_CONFIG_VERSION
        changed = True

    # --------------------------------------------------------
    # Migrate old "enabled" setting to "remove_spaces".
    # --------------------------------------------------------

    if (
        "remove_spaces" not in settings
        and "enabled" in settings
    ):

        settings["remove_spaces"] = bool(
            settings["enabled"]
        )

        del settings["enabled"]

        changed = True

    if "remove_spaces" not in settings:
        settings["remove_spaces"] = False
        changed = True

    if "paste_as_plain_text" not in settings:
        settings["paste_as_plain_text"] = False
        changed = True

    if "paste_media_links" not in settings:
        settings["paste_media_links"] = False
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

    # Never save the old setting name.
    settings.pop(
        "enabled",
        None,
    )

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
# Load configuration
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

paste_media_links = bool(
    settings.get(
        "paste_media_links",
        False,
    )
)


# ============================================================
# Editor tracking
# ============================================================

editors = []


# ============================================================
# Media URL detection
# ============================================================

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
    ".avif",
}

AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".ogg",
    ".oga",
    ".opus",
    ".m4a",
    ".aac",
    ".flac",
    ".weba",
}


def get_media_type_from_url(url):
    """
    Determine whether a URL appears to point to an image
    or audio file.

    Returns:

        "image"
        "audio"
        None
    """

    # Remove query string and fragment.
    clean_url = url.split("?", 1)[0]
    clean_url = clean_url.split("#", 1)[0]

    clean_url = clean_url.lower()

    for extension in IMAGE_EXTENSIONS:

        if clean_url.endswith(extension):
            return "image"

    for extension in AUDIO_EXTENSIONS:

        if clean_url.endswith(extension):
            return "audio"

    return None


def extract_media_url(text):
    """
    Extract a single HTTP/HTTPS media URL from clipboard text.

    Only a single URL is accepted. This prevents accidentally
    converting arbitrary text containing a URL.
    """

    if not text:
        return None

    text = text.strip()

    # Must be exactly one URL.
    match = re.fullmatch(
        r"https?://\S+",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    url = match.group(0)

    # Remove common punctuation accidentally copied after
    # the URL.
    url = url.rstrip(
        ".,;:!?)]}>\"'"
    )

    if get_media_type_from_url(url) is None:
        return None

    return url


# ============================================================
# Download media from URL
# ============================================================

def download_media(url):
    """
    Download media from a URL.

    Returns:

        (data, content_type)

    or:

        (None, None)
    """

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Anki Clipboard Controls)"
                )
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=15,
        ) as response:

            data = response.read()

            content_type = response.headers.get(
                "Content-Type",
                "",
            )

        return data, content_type

    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
    ) as error:

        print(
            "Clipboard Controls: "
            f"Could not download media URL: "
            f"{url} ({error})"
        )

        return None, None

    except Exception as error:

        print(
            "Clipboard Controls: "
            f"Unexpected download error: "
            f"{url} ({error})"
        )

        return None, None


# ============================================================
# URL -> MIME data
# ============================================================

def convert_media_url_to_mime(mime):
    """
    If the clipboard contains a direct image/audio URL,
    download it and replace the clipboard data with the
    corresponding binary media.

    This allows Anki to process it like normal pasted media.
    """

    if not paste_media_links:
        return mime

    if not mime.hasText():
        return mime

    text = mime.text()

    url = extract_media_url(text)

    if not url:
        return mime

    media_type = get_media_type_from_url(url)

    if media_type not in (
        "image",
        "audio",
    ):
        return mime

    print(
        "Clipboard Controls: "
        f"Downloading {media_type}: {url}"
    )

    data, content_type = download_media(url)

    if not data:
        return mime

    # --------------------------------------------------------
    # Create a new MIME object.
    # --------------------------------------------------------

    new_mime = QMimeData()

    # Keep the original URL as text as a fallback.
    new_mime.setText(text)


    # --------------------------------------------------------
    # Image.
    # --------------------------------------------------------

    if media_type == "image":

        # Qt accepts image bytes through imageData.
        new_mime.setData(
            content_type
            if content_type.startswith("image/")
            else "image/png",
            QByteArray(data),
        )

        return new_mime


    # --------------------------------------------------------
    # Audio.
    # --------------------------------------------------------

    if media_type == "audio":

        if (
            not content_type
            or not content_type.startswith("audio/")
        ):

            extension = (
                url
                .split("?", 1)[0]
                .split("#", 1)[0]
                .lower()
            )

            if extension.endswith(".mp3"):
                content_type = "audio/mpeg"

            elif extension.endswith(".wav"):
                content_type = "audio/wav"

            elif extension.endswith(".ogg"):
                content_type = "audio/ogg"

            elif extension.endswith(".oga"):
                content_type = "audio/ogg"

            elif extension.endswith(".opus"):
                content_type = "audio/opus"

            elif extension.endswith(".m4a"):
                content_type = "audio/mp4"

            elif extension.endswith(".aac"):
                content_type = "audio/aac"

            elif extension.endswith(".flac"):
                content_type = "audio/flac"

            elif extension.endswith(".weba"):
                content_type = "audio/webm"

            else:
                content_type = "application/octet-stream"


        new_mime.setData(
            content_type,
            QByteArray(data),
        )

        return new_mime


    return mime


# ============================================================
# Anki MIME hook
# ============================================================

def editor_will_process_mime(
    mime,
    editor_web_view,
    internal,
    extended,
    drop_event,
):
    """
    Convert direct image/audio URLs into media before Anki
    processes the paste.
    """

    if internal:
        return mime

    if drop_event:
        return mime

    return convert_media_url_to_mime(
        mime
    )


gui_hooks.editor_will_process_mime.append(
    editor_will_process_mime
)


# ============================================================
# JavaScript paste handler
# ============================================================

PASTE_HANDLER = r"""
(function() {

    // --------------------------------------------------------
    // Remove an existing handler first.
    // --------------------------------------------------------

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


    // --------------------------------------------------------
    // Detect native media.
    // --------------------------------------------------------

    function clipboardContainsNativeMedia(clipboard) {

        if (clipboard.types) {

            for (
                let i = 0;
                i < clipboard.types.length;
                i++
            ) {

                const type =
                    clipboard.types[i].toLowerCase();


                if (
                    type.startsWith("image/")
                ) {
                    return true;
                }


                if (
                    type.startsWith("audio/")
                ) {
                    return true;
                }


                if (
                    type.startsWith("video/")
                ) {
                    return true;
                }
            }
        }


        if (clipboard.items) {

            for (
                let i = 0;
                i < clipboard.items.length;
                i++
            ) {

                const item =
                    clipboard.items[i];


                if (
                    item.kind === "file" &&
                    item.type
                ) {

                    const type =
                        item.type.toLowerCase();


                    if (
                        type.startsWith("image/") ||
                        type.startsWith("audio/") ||
                        type.startsWith("video/")
                    ) {
                        return true;
                    }
                }
            }
        }


        return false;
    }


    // --------------------------------------------------------
    // Detect a direct media URL.
    //
    // These must be allowed through so Anki's Python
    // editor_will_process_mime hook can download them.
    // --------------------------------------------------------

    function looksLikeMediaURL(text) {

        if (!text) {
            return false;
        }

        text = text.trim();


        if (
            !/^https?:\/\/\S+$/i.test(text)
        ) {
            return false;
        }


        text = text
            .replace(/[.,;:!?)]}>\"']+$/, "")
            .toLowerCase();


        return (
            /\.(jpg|jpeg|png|gif|webp|bmp|svg|avif)(\?|#|$)/i.test(text) ||
            /\.(mp3|wav|ogg|oga|opus|m4a|aac|flac|weba)(\?|#|$)/i.test(text)
        );
    }


    // --------------------------------------------------------
    // Paste handler.
    // --------------------------------------------------------

    window.removeSpacesPasteHandler =
        function(event) {

            const removeSpaces =
                window.removeSpacesPasteEnabled === true;

            const pasteAsPlainText =
                window.pasteAsPlainTextEnabled === true;

            const pasteMediaLinks =
                window.pasteMediaLinksEnabled === true;


            // Nothing enabled.
            if (
                !removeSpaces &&
                !pasteAsPlainText &&
                !pasteMediaLinks
            ) {
                return;
            }


            const clipboard =
                event.clipboardData;


            if (!clipboard) {
                return;
            }


            // ------------------------------------------------
            // Let Anki handle actual images/audio/video.
            // ------------------------------------------------

            if (
                clipboardContainsNativeMedia(
                    clipboard
                )
            ) {
                return;
            }


            // ------------------------------------------------
            // If this is a media URL and media-link pasting
            // is enabled, allow Anki's Python MIME hook to
            // process it.
            // ------------------------------------------------

            if (
                pasteMediaLinks &&
                looksLikeMediaURL(
                    clipboard.getData("text/plain")
                )
            ) {
                return;
            }


            // ------------------------------------------------
            // Get plain text.
            // ------------------------------------------------

            let text =
                clipboard.getData(
                    "text/plain"
                );


            if (
                text === null ||
                text === undefined
            ) {
                return;
            }


            // ------------------------------------------------
            // Remove whitespace.
            // ------------------------------------------------

            if (removeSpaces) {

                text = text.replace(
                    /\s/g,
                    ""
                );
            }


            // ------------------------------------------------
            // Intercept text/HTML paste.
            // ------------------------------------------------

            event.preventDefault();

            event.stopPropagation();

            event.stopImmediatePropagation();


            // ------------------------------------------------
            // Insert plain text.
            // ------------------------------------------------

            document.execCommand(
                "insertText",
                false,
                text
            );
        };


    // --------------------------------------------------------
    // Install handler.
    // --------------------------------------------------------

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

    paste_media_links_value = (
        "true"
        if paste_media_links
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

    editor.web.eval(
        "window.pasteMediaLinksEnabled = "
        f"{paste_media_links_value};"
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

        self.setMinimumWidth(380)

        layout = QVBoxLayout()

        current_settings = load_settings()


        # ----------------------------------------------------
        # Remove spaces
        # ----------------------------------------------------

        self.remove_spaces_checkbox = QCheckBox(
            "Remove spaces when pasting"
        )

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
        # Paste media links
        # ----------------------------------------------------

        self.paste_media_links_checkbox = QCheckBox(
            "Paste image/audio links as media"
        )

        self.paste_media_links_checkbox.setChecked(
            bool(
                current_settings.get(
                    "paste_media_links",
                    False,
                )
            )
        )

        layout.addWidget(
            self.paste_media_links_checkbox
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
        global paste_media_links
        global settings


        # ----------------------------------------------------
        # Read settings.
        # ----------------------------------------------------

        remove_spaces = (
            self.remove_spaces_checkbox.isChecked()
        )

        paste_as_plain_text = (
            self.plain_text_checkbox.isChecked()
        )

        paste_media_links = (
            self.paste_media_links_checkbox.isChecked()
        )


        # ----------------------------------------------------
        # Save settings.
        # ----------------------------------------------------

        settings["version"] = (
            CURRENT_CONFIG_VERSION
        )

        settings["remove_spaces"] = (
            remove_spaces
        )

        settings["paste_as_plain_text"] = (
            paste_as_plain_text
        )

        settings["paste_media_links"] = (
            paste_media_links
        )


        save_settings(
            settings
        )


        # ----------------------------------------------------
        # Update existing editors.
        # ----------------------------------------------------

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