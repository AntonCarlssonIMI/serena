# SPDX-License-Identifier: MIT
"""
PL/SQL language server communicating via stdio.

Run with ``python -m solidlsp.language_servers.plsql.server``.
"""

import logging
import sys

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer


class PlsqlServer(LanguageServer):
    """
    Language server for Oracle PL/SQL.
    """

    INDEX_READY_MESSAGE = "PL/SQL workspace index ready"
    """the prefix of the log message that is sent to the client once the workspace has been indexed"""

    def __init__(self) -> None:
        super().__init__("plsql-lsp", "0.1.0")
        self._register_features()

    def _register_features(self) -> None:
        @self.feature(lsp.INITIALIZED)
        def initialized(params: lsp.InitializedParams) -> None:
            self.window_log_message(lsp.LogMessageParams(type=lsp.MessageType.Info, message=self.INDEX_READY_MESSAGE))


def main() -> None:
    """
    Runs the PL/SQL language server on stdin/stdout.
    """
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    PlsqlServer().start_io()


if __name__ == "__main__":
    main()
