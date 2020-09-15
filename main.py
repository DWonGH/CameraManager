import os
import argparse

from stream_manager import CameraManager

cwd = os.path.abspath(os.getcwd())

parser = argparse.ArgumentParser()

parser.add_argument("--width", help="Camera width resolution", default=1280)
parser.add_argument("--height", help="Camera height resolution", default=720)
parser.add_argument("--fps", help="Camera frames per second (fps)", default=15)
parser.add_argument("--flip", dest='flip', action='store_true', help="True to flip the image vertically")
parser.add_argument("--display", dest='display', action='store_true', help="Display stream outputs")
parser.add_argument("--control_room", dest='control_room', action='store_true',
                    help="Adjust output windows to match control room monitor size (False means lab monitor)")
parser.add_argument("--record", dest='record', action='store_true', help="Enable video writers")
parser.add_argument('--devices', action='store', dest='devices',
                    type=str, nargs='*', default=[],
                    help="Examples: -i item1 item2, -i item3")
parser.add_argument("--snapshot", dest='snapshot', action='store_true', help="Turns on snapshot mode")
parser.add_argument("--countdown", default=3, type=int, help="Do a countdown in seconds before taking a snapshot")
parser.add_argument("--num_snapshots", default=1, type=int, help="Take several pictures")
parser.add_argument("--interval", default=1, type=int, help="Pause(in seconds) between taking snapshots")
parser.add_argument("--save_params", dest='save_params', action='store_true', help="Write the enabled cameras paramters to output file")

args = parser.parse_args()


camera_manager = CameraManager(args.width, args.height, args.fps, args.flip, args.display,
                               args.record, args.control_room, args.devices, args.snapshot_timer, args.num_snapshots,
                               args.interval, args.snapshot, args.save_params)
