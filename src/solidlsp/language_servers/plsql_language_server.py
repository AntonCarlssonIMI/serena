# SPDX-License-Identifier: MIT
"""
Provides Oracle PL/SQL specific instantiation of the SolidLanguageServer class, backed by the PL/SQL language
server implemented in :mod:`solidlsp.language_servers.plsql`.
"""

from solidlsp.language_servers.indexing_server.adapter import IndexingServerAdapter
from solidlsp.language_servers.indexing_server.server import IndexingLanguageServer
from solidlsp.language_servers.plsql.server import PlsqlServer
from solidlsp.ls_config import LanguageServerConfig
from solidlsp.settings import SolidLSPSettings


class PlsqlLanguageServer(IndexingServerAdapter):
    """
    Oracle PL/SQL language server, running the PL/SQL server shipped with SolidLSP in a subprocess.
    The default source extensions are ``.pks``, ``.pkb`` and ``.pck``.
    """

    def __init__(self, config: LanguageServerConfig, repository_root_path: str, solidlsp_settings: SolidLSPSettings):
        super().__init__(config, repository_root_path, solidlsp_settings, "plsql")

    @classmethod
    def _get_server_class(cls) -> type[IndexingLanguageServer]:
        return PlsqlServer
