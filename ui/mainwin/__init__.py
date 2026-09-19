# ui/mainwin — MainWindow 기능별 믹스인 패키지
from ui.mainwin.tabs import TabsMixin
from ui.mainwin.panels import PanelsMixin
from ui.mainwin.find_nav import FindNavMixin
from ui.mainwin.view_modes import ViewModesMixin
from ui.mainwin.text_draft import TextDraftMixin
from ui.mainwin.file_ops import FileOpsMixin
from ui.mainwin.page_ops import PageOpsMixin
from ui.mainwin.edit_ops import EditOpsMixin
from ui.mainwin.snapshot import SnapshotMixin
from ui.mainwin.annot_menu import AnnotMenuMixin
from ui.mainwin.autosave import AutosaveMixin
from ui.mainwin.security import SecurityMixin

__all__ = [
    'TabsMixin',
    'PanelsMixin',
    'FindNavMixin',
    'ViewModesMixin',
    'TextDraftMixin',
    'FileOpsMixin',
    'PageOpsMixin',
    'EditOpsMixin',
    'SnapshotMixin',
    'AnnotMenuMixin',
    'AutosaveMixin',
    'SecurityMixin',
]
