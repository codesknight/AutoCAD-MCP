"""Opt-in stdio test launcher pinned to a manually loaded NativeTests PID.

For isolated Cader regression only. No production instance discovery, automatic
CAD launch, fallback, permission change, or Cader source modification.
"""
import argparse

from autocad_mcp.cad.capture import prop
from autocad_mcp.cad.connection import CADConnection
from autocad_mcp.config import load_config
from scripts.native_test_target import application


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid",type=int,required=True)
    args=parser.parse_args()
    if load_config().backend!="com":raise RuntimeError("Fixture launcher requires explicit COM configuration")
    def attach(connection,*,allow_launch=True):
        connection.app=application(args.pid)
        if prop(prop(connection.app,"Documents"),"Count"):
            connection._wait_for_document(connection.config.connect_timeout)
        else:connection.document=connection.model_space=None
    CADConnection.connect=attach
    from autocad_mcp.server import mcp
    mcp.run()


if __name__=="__main__":main()
