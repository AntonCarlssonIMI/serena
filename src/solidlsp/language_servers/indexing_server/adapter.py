# SPDX-License-Identifier: MIT
"""
Base class of the SolidLSP adapters for language servers derived from :class:`IndexingLanguageServer`.
"""

import logging
import sys
import threading
from abc import ABC, abstractmethod

from solidlsp.dependency_provider import LanguageServerDependencyProvider, LanguageServerDependencyProviderBaseCommand
from solidlsp.language_servers.indexing_server.server import IndexingLanguageServer
from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_config import LanguageServerConfig
from solidlsp.settings import SolidLSPSettings

log = logging.getLogger(__name__)


class IndexingServerAdapter(SolidLanguageServer, ABC):
    """
    Language server running an :class:`IndexingLanguageServer` shipped with SolidLSP in a subprocess
    (no installation required).

    LS-specific settings:

      * ``file_extensions``: further file extensions (e.g. ``[".spec", ".body"]``) to treat as sources,
        in addition to the language's default extensions
    """

    _INDEX_READY_TIMEOUT_SECONDS = 600.0

    class DependencyProvider(LanguageServerDependencyProviderBaseCommand):
        """
        Launches a server module with the Python interpreter running SolidLSP.
        """

        def __init__(self, custom_settings: SolidLSPSettings.CustomLSSettings, ls_resources_dir: str, server_module: str) -> None:
            """
            :param custom_settings: the (user-provided) language server-specific settings
            :param ls_resources_dir: the directory in which data for the language server shall be stored
            :param server_module: the fully qualified name of the module that runs the server when executed
            """
            super().__init__(custom_settings, ls_resources_dir)
            self._server_module = server_module

        def _create_default_base_command(self) -> list[str]:
            # -P: the server runs in the project directory, whose modules must not shadow the server's imports
            return [sys.executable, "-P", "-m", self._server_module]

        def _create_launch_command_from_base_command(self, base_command: list[str]) -> list[str]:
            return base_command

    def __init__(self, config: LanguageServerConfig, repository_root_path: str, solidlsp_settings: SolidLSPSettings, language_id: str):
        """
        :param config: the language server configuration
        :param repository_root_path: the root path of the repository
        :param solidlsp_settings: the SolidLSP settings
        :param language_id: the LSP language identifier of the sources
        """
        super().__init__(config, repository_root_path, None, language_id, solidlsp_settings)
        self._sync_source_fn_matcher()
        self._index_ready = threading.Event()

    @classmethod
    @abstractmethod
    def _get_server_class(cls) -> type[IndexingLanguageServer]:
        """
        :return: the server class, whose module runs the server when executed
        """

    def _sync_source_fn_matcher(self) -> None:
        """
        Adds the configured ``file_extensions`` to the source-file matcher, such that Serena and the server
        (which receives the matcher's extensions) treat the same files as sources.
        """
        file_extensions = self._custom_settings.get("file_extensions", [])
        if not isinstance(file_extensions, list):
            log.warning("The 'file_extensions' setting should be a list of strings. Ignoring the provided value: %s", file_extensions)
            return
        normalised = [extension if extension.startswith(".") else f".{extension}" for extension in map(str, file_extensions)]
        self.ls_id.get_source_fn_matcher().add_extensions(*normalised)

    def _create_dependency_provider(self) -> LanguageServerDependencyProvider:
        return self.DependencyProvider(self._custom_settings, self._ls_resources_dir, self._get_server_class().__module__)

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
        ready_message = self._get_server_class().INDEX_READY_MESSAGE
        server_name = type(self).__name__

        def on_log_message(params: dict) -> None:
            message = params.get("message", "")
            log.info("%s LS: %s", server_name, message)
            if message.startswith(ready_message):
                self._index_ready.set()

        def ignore_diagnostics(params: dict) -> None:
            pass

        self.server.on_notification("window/logMessage", on_log_message)
        self.server.on_notification("textDocument/publishDiagnostics", ignore_diagnostics)

        # start the server and wait until it has indexed the workspace
        self.server.start()
        init_response = self.server.send.initialize(self._create_initialize_params())
        log.debug("%s LS initialize response: %s", server_name, init_response)
        self.server.notify.initialized({})
        if not self._index_ready.wait(timeout=self._INDEX_READY_TIMEOUT_SECONDS):
            log.warning("%s LS did not report a ready index within %s seconds; proceeding", server_name, self._INDEX_READY_TIMEOUT_SECONDS)
