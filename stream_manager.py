import time
import datetime
import os
import regex as re
import json

import pyrealsense2 as rs
import numpy as np
import cv2

from realsense_device_manager import DeviceManager


class CameraManager:

    def __init__(self, width, height, fps, flip, display, record, lab_monitor, specified_devices,
                 snapshot_timer, num_snapshots, snapshot_interval, snapshot_mode, save_params):
        """
        Manage the RealSense output streams
        """
        self.width = width  # Resolution
        self.height = height  # Resolution
        self.fps = fps  # Frame rate
        self.flip = flip  # True to flip cameras vertically when in the living lab
        self.display = display  # True to enable display windows
        self.record = record  # True to enable video writers
        self.lab_monitor = lab_monitor  # Adjust display window sizes for control room or lab monitors (i.e. high / low resolution monitors)
        self.specified_devices = specified_devices  # A list of specified camera serial numbers to be run
        self.snapshot_mode = snapshot_mode  # True to take pictures instead of videos
        self.snapshot_timer = snapshot_timer  # Countdown in seconds till picture taken
        self.num_snapshots = num_snapshots  # How many pictures to take
        self.snapshot_interval = snapshot_interval  # Time in seconds between pictures
        self.save_params = save_params

        assert width > 0, "Invalid width resolution"
        assert height > 0, "Invalid height resolution"
        assert fps > 0, "Invalid frames per second (fps)"
        if self.record:
            assert not self.snapshot_mode, "Should only use record when in video mode (not snapshot mode)"
        if self.snapshot_mode:
            assert not self.record, "Should only use record when in video mode (not snapshot mode)"
            assert self.num_snapshots > 0
            assert self.snapshot_interval >= 0
            assert self.snapshot_timer >= 0

        # Prepare specified configuration (depth & infrared not implemented)
        self.rs_config = rs.config()  # For initialising RealSense
        self.rs_config.enable_stream(rs.stream.color, self.width, self.height, rs.format.bgr8, self.fps)

        # Load the RealSense devices
        self.device_manager = DeviceManager(rs.context(), self.rs_config)
        if len(self.specified_devices) > 0:
            self.device_manager.enable_specified_devices(self.specified_devices)
        else:
            self.device_manager.enable_all_devices()
        assert (len(self.device_manager._available_devices) > 0), \
            "Camera initialisation failed; there are no available devices"

        self.enabled_devices = []
        all(self.enabled_devices.append(serial) for (serial, device) in self.device_manager._enabled_devices.items())
        for device in self.specified_devices:
            assert device in self.enabled_devices, "Specified device is not connected / failed to connect"

        # Set window positions for known cameras based on integer tiling in a 3x3 grid, roughly reflecting their
        # positions in the lab:
        if self.lab_monitor:
            self.default_win_size = (int(1920/3), int(1080/3))  # Good for 1920x1080 display, e.g. monitor in control room
        else:
            self.default_win_size = (int(1920/5), int(1080/5))  # Good for Living Lab TV when using low resolution.

        self.default_win_pos = {
            '2': (2, 2),  # Right, bottom
            '3': (2, 1),  # Middle, bottom
            '4': (2, 0),  # Right, top
            '5': (1, 2),  # Middle, bottom
            '6': (1, 1),  # Middle, middle
            '7': (0, 2),  # Left, bottom
            '8': (0, 0),  # Left, top
        }

        # Convert window positions to pixels
        for key in self.default_win_pos:
            self.default_win_pos[key] = tuple([x * self.default_win_size[i] for i, x in enumerate(self.default_win_pos[key])])

        # This allows simplified window naming and consistent window positioning between runs.
        # If cameras are moved around in the lab, these should be changed.
        self.cam_names = {
            "830112071467": '5',
            "830112071329": '4',
            "831612070394": '2',
            "831612071422": '3',
            "831612071440": '8',
            "831612071526": 'X'
            }

        self.display_windows = {}
        self.video_writers = {}

        # Configure the output directory for recordings
        now = datetime.datetime.now()
        if not os.path.exists(os.path.join(os.getcwd(), "recordings")):
            os.mkdir(os.path.join(os.getcwd(), "recordings"))
        if self.record or self.save_params or self.snapshot_mode:
            self.output_directory = os.path.join(os.getcwd(), "recordings", now.strftime('20%y-%m-%d-%H-%M'))
            if os.path.exists(self.output_directory):
                while os.path.exists(self.output_directory):
                    self.output_directory += "a"
            os.mkdir(self.output_directory)
            assert os.path.exists(self.output_directory)

        # Wait for exposure to balance
        print("Warming up")
        self.warm_up()

        # Write each cameras parameters to json file
        if self.save_params:
            self.save_intrinsics(self.output_directory, self.device_manager.poll_frames())

        print("Loaded lab manager " + str(self.width) + " " + str(self.height) + " " + str(self.fps))

        # Start streaming
        if self.snapshot_mode:
            self.snapshot()
        elif self.display or self.record:
            self.stream()
        else:
            return None

    def snapshot(self):
        """
        Creates a new timestamped folder and saves a single jpg image from each camera.
        A countdown can be specified before the first snapshot and then several snapshots
        can be taken at regular intervals.
        """

        for device in self.enabled_devices:
            os.mkdir(os.path.join(self.output_directory, device))
        print(f"Saving snapshots to {self.output_directory}")
        assert len(next(os.walk(self.output_directory))[1]) == len(self.enabled_devices), \
            f"There should be a single directory for each device in {self.output_directory}"

        if self.snapshot_timer:
            print(f"Taking snapshots in...")
            for i in range(self.snapshot_timer, 0, -1):
                time.sleep(1)
                print(i)

        if self.display:
            self.load_display_windows()

        for snap in range(self.num_snapshots):
            frames_devices = self.device_manager.poll_frames()
            for i, (device, frame) in enumerate(frames_devices.items()):
                if self.flip:
                    final_frame = self.flip_frame(frame)
                else:
                    final_frame = np.asarray(frame[rs.stream.color].get_data())
                cv2.imwrite(os.path.join(self.output_directory, device, f"{snap}.jpg"), final_frame)
                if self.display:
                    window = self.display_windows[device]
                    cv2.imshow(window, final_frame)
                    ret = cv2.waitKey(1)
            time.sleep(self.snapshot_interval)
        self.stop()

    def stream(self):
        """
        Writes or displays all available video streams
        :param frames_devices: Dictionary from device manager (with latest polled frames)
        :param flip: Select true for right way up
        :return: None
        """
        if self.record: self.load_video_writers()
        if self.display: self.load_display_windows()
        try:
            while True:
                frames_devices = self.device_manager.poll_frames()
                for i, (device, frame) in enumerate(frames_devices.items()):
                    if self.flip:
                        final_frame = self.flip_frame(frame)
                    else:
                        final_frame = np.asarray(frame[rs.stream.color].get_data())
                    if self.record:
                        writer = self.video_writers[device]
                        writer.write(final_frame)
                    if self.display:
                        window = self.display_windows[device]
                        cv2.imshow(window, final_frame)
                        ret = cv2.waitKey(1)
        except KeyboardInterrupt:
            print("Ctrl+C quit")
        finally:
            self.stop()

    def load_video_writers(self):
        """
        Creates a new timestamped folder and loads a new video writer for each enabled device
        """
        for device in self.device_manager._enabled_devices:
            os.mkdir(os.path.join(self.output_directory, device))
            print(f"Writing videos to {os.path.join(self.output_directory, device)}")
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            writer = cv2.VideoWriter(os.path.join(self.output_directory, device, f"1.avi"), fourcc, self.fps, (self.width, self.height))
            self.video_writers[device] = writer

    def load_display_windows(self):
        """
        Creates a window for each enabled device,
        saves the window into the 'self.display_windows = {}'
        -------
        :param enabled_devices: The devices passed from the device manager
        :return: None
        """
        print(f"Displaying video outputs")
        for device in self.device_manager._enabled_devices:
            # If we don't know the name of this device, use its serial number.
            if device not in self.cam_names:
                self.cam_names[device] = device
            win_name = 'Camera ' + self.cam_names[device]
            self.display_windows[device] = win_name
            cv2.namedWindow(win_name,cv2.WINDOW_NORMAL)  # cv2.WINDOW_NORMAL enables explicit sizing, as opposed to cv2.WINDOW_AUTOSIZE.
            cv2.resizeWindow(win_name, self.default_win_size)
            if self.cam_names[device] in self.default_win_pos:
                cv2.moveWindow(win_name, self.default_win_pos[self.cam_names[device]][0],
                               self.default_win_pos[self.cam_names[device]][1])

    def warm_up(self):
        """
        Run the camera to allow exposure adjustment
        """
        for frame in range(25):
            frames = self.device_manager.poll_frames()
            time.sleep(0.1)

    def flip_frame(self, frame):
        """
        Takes a frame and flips horizontally & vertically.
        :param frame: Given frame data, a 3d array from the device stream
        :return:
        """
        array = np.asarray(frame[rs.stream.color].get_data())
        flip_h = np.fliplr(array)
        flip_v = np.flipud(flip_h)
        return flip_v

    def close_streams(self):
        """
        Finish up output streams
        :return:
        """
        if self.display_windows:
            cv2.destroyAllWindows()
        if self.video_writers:
            for device, writer in self.video_writers.items():
                writer.release()

    def stop(self):
        """
        Disconnects the devices and stops the streams etc.
        """
        print("Closing streams...")
        self.device_manager.disable_streams()
        self.close_streams()
        print("Done.")

    def save_intrinsics(self, directory, frames_devices):
        """
        Write the intrinsic parameters of each enabled device to a json file
        :param directory:
        :param frames_devices:
        :return:
        """
        # Get the intrinsic information from the device manager for each camera
        grabbed_intrinsics = self.stringify_keys(self.device_manager.get_device_intrinsics(frames_devices))

        # Then tidy it up and write it to a json file with the corresponding pictures
        clean_intrinsics = {}
        for camera, streams in grabbed_intrinsics.items():
            print(f"Camera {camera}")
            for stream in streams:
                print(f"Parameters {streams[stream]}")
                params = streams[stream].split('p')
                res = re.findall("\[(.*?)\]", params[1])
                clean_intrinsics[camera] = {
                    'fx': res[1].split(" ")[0],
                    'fy': res[1].split(" ")[1],
                    'cx': res[0].split(" ")[0],
                    'cy': res[0].split(" ")[1],
                    'd1': res[2].split(" ")[0],
                    'd2': res[2].split(" ")[1],
                    'd3': res[2].split(" ")[2],
                    'd4': res[2].split(" ")[3],
                    'd5': res[2].split(" ")[4]
                }
        with open(os.path.join(directory, 'intrinsics.json'), 'w') as fp:
            json.dump(clean_intrinsics, fp)

    def stringify_keys(self, d):
        """
        Convert a dict's keys to strings if they are not.
        """
        for key in d.keys():

            # check inner dict
            if isinstance(d[key], dict):
                value = self.stringify_keys(d[key])
            else:
                value = d[key]

            # convert nonstring to string if needed
            if not isinstance(key, str):
                try:
                    d[str(key)] = value
                except Exception:
                    try:
                        d[repr(key)] = value
                    except Exception:
                        raise

                # delete old key
                del d[key]
        return d