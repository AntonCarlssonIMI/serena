"""
Integration tests for the PL/SQL language server, using the default file extensions.
"""

import pytest

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import LanguageServerId

pytestmark = [pytest.mark.plsql]


@pytest.mark.parametrize("language_server", [LanguageServerId.PLSQL], indirect=True)
def test_ls_is_running(language_server: SolidLanguageServer) -> None:
    assert language_server.is_running()
