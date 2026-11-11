# SPDX-License-Identifier: MIT
"""
Provides NASM assembly specific instantiation of the SolidLanguageServer class, backed by the NASM language
server implemented in :mod:`solidlsp.language_servers.nasm`.
"""

from solidlsp.language_servers.indexing_server.adapter import IndexingServerAdapter
from solidlsp.language_servers.indexing_server.server import IndexingLanguageServer
from solidlsp.language_servers.nasm.server import NasmServer
from solidlsp.ls_config import LanguageServerConfig
from solidlsp.settings import SolidLSPSettings


class NasmLanguageServer(IndexingServerAdapter):
    """
    NASM assembly language server, running the NASM server shipped with SolidLSP in a subprocess.
    The default source extensions are ``.asm``, ``.nasm``, ``.inc`` and ``.mac``.
    """

    def __init__(self, config: LanguageServerConfig, repository_root_path: str, solidlsp_settings: SolidLSPSettings):
        super().__init__(config, repository_root_path, solidlsp_settings, "nasm")

    @classmethod
    def _get_server_class(cls) -> type[IndexingLanguageServer]:
        return NasmServer
