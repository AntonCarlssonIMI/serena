# SPDX-License-Identifier: MIT
"""
Provides Oracle PL/SQL specific instantiation of the SolidLanguageServer class, backed by the PL/SQL language
server implemented in :mod:`solidlsp.language_servers.plsql`.
"""

import logging
import sys
import threading

from solidlsp.dependency_provider import LanguageServerDependencyProvider, LanguageServerDependencyProviderBaseCommand
from solidlsp.language_servers.plsql.server import PlsqlServer
from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_config import LanguageServerConfig
from solidlsp.settings import SolidLSPSettings

log = logging.getLogger(__name__)


class PlsqlLanguageServer(SolidLanguageServer):
    """
    Oracle PL/SQL language server, running the PL/SQL server shipped with SolidLSP in a subprocess.

    LS-specific settings:

      * ``file_extensions``: further file extensions (e.g. ``[".spec", ".body"]``) to treat as PL/SQL sources,
        in addition to ``.pks``, ``.pkb`` and ``.pck``
    """

    _INDEX_READY_TIMEOUT_SECONDS = 600.0

    class DependencyProvider(LanguageServerDependencyProviderBaseCommand):
        """
        Launches the PL/SQL server module with the Python interpreter running SolidLSP (no installation required).
        """

        def _create_default_base_command(self) -> list[str]:
            return [sys.executable, "-m", "solidlsp.language_servers.plsql.server"]

        def _create_launch_command_from_base_command(self, base_command: list[str]) -> list[str]:
            return base_command

    def __init__(self, config: LanguageServerConfig, repository_root_path: str, solidlsp_settings: SolidLSPSettings):
        super().__init__(config, repository_root_path, None, "plsql", solidlsp_settings)
        self._index_ready = threading.Event()

    def _create_dependency_provider(self) -> LanguageServerDependencyProvider:
        return self.DependencyProvider(self._custom_settings, self._ls_resources_dir)

    def _create_base_initialize_params(self) -> dict:
        return {
            "capabilities": {
                "textDocument": {
                    "synchronization": {"didSave": True, "dynamicRegistration": True},
                    "documentSymbol": {
                        "hierarchicalDocumentSymbolSupport": True,
                        "symbolKind": {"valueSet": list(range(1, 27))},
                    },
                    "definition": {"dynamicRegistration": True},
                    "references": {"dynamicRegistration": True},
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                },
                "workspace": {"workspaceFolders": True, "symbol": {"dynamicRegistration": True}},
            },
            "initializationOptions": {
                "fileExtensions": self.get_source_fn_matcher().file_extensions,
                "encoding": self._encoding,
            },
        }

    def _start_server(self) -> None:
        def on_log_message(params: dict) -> None:
            message = params.get("message", "")
            log.info("PL/SQL LS: %s", message)
            if message.startswith(PlsqlServer.INDEX_READY_MESSAGE):
                self._index_ready.set()

        def ignore_diagnostics(params: dict) -> None:
            pass

        self.server.on_notification("window/logMessage", on_log_message)
        self.server.on_notification("textDocument/publishDiagnostics", ignore_diagnostics)

        # start the server and wait until it has indexed the workspace
        self.server.start()
        init_response = self.server.send.initialize(self._create_initialize_params())
        log.debug("PL/SQL LS initialize response: %s", init_response)
        self.server.notify.initialized({})
        if not self._index_ready.wait(timeout=self._INDEX_READY_TIMEOUT_SECONDS):
            log.warning("PL/SQL LS did not report a ready index within %s seconds; proceeding", self._INDEX_READY_TIMEOUT_SECONDS)
