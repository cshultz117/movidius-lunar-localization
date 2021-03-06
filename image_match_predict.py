# imports
import sys
import os
import time
import numpy as np
import math
import logging as log
# argument parsing
from argparse import ArgumentParser, SUPPRESS
# multithreading
import threading
# interface
import tkinter as tk
from PIL import Image, ImageTk
# tensorflow
import tensorflow as tf
import tensorflow_hub as hub
# openvino
from openvino.inference_engine import IENetwork, IECore
import cv2 as cv
# stepper motor
import subprocess
import yaml



PREDICT_BATCH_SIZE = 1
LMBDA = 100
INPUT_WIDTH = 224
INPUT_HEIGHT = 224
PREDICT_DATASET='./reproject_truematch_allbatch_5050match_224scale_06iou.tfr'
MODEL_XML = "./ovino_model/resnet50v2.xml"
MODEL_BIN = os.path.splitext(MODEL_XML)[0] + ".bin"
CAMERA_DEVICE_NUMBER = 0
ARGS = None

tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.INFO)
tf.compat.v1.disable_eager_execution()



# parse command line arguments
def build_argparser():

    parser = ArgumentParser(add_help=False)
    args = parser.add_argument_group('Options')
    args.add_argument('-h', '--help', action='help', default=SUPPRESS, help='Show this help message and exit.')
    args.add_argument("-d", "--device",
                      help="Optional. Specify the target device to infer on; CPU, GPU, FPGA, HDDL or MYRIAD is"
                           " acceptable. The sample will look for a suitable plugin for device specified. "
                           "Default value is MYRIAD", default="MYRIAD", type=str)

    return parser



# stepper motor controller (requires ticcmd binary
def ticcmd(*args):
  return subprocess.check_output(['ticcmd'] + list(args))



###### BEGIN FDL REPROJECTION SCRIPT
# source: https://gitlab.com/frontierdevelopmentlab/space-resources/sr2018-localization-public/blob/master/DataProcessing/batch_reproj.py
# original code modified for images in memory rather than storage

def reproj_fn(views):
    quiet_operation = True

    # camera intrinsic values
    specs0 = {'fov_y': None, 'fov_x': 90, 'camera_height': 2, 'camera_pitch': -15,
              'rover_pitch': 0, 'rover_roll': 0, 'camera_yaw' : 0,
              'desired_resolution': 0.05, 'minimum_resolution' : None, 'output_region_size': 50,}
    specs1 = {'fov_y': None, 'fov_x': 90, 'camera_height': 2, 'camera_pitch': -15,
              'rover_pitch': 0, 'rover_roll': 0, 'camera_yaw': 90,
              'desired_resolution': 0.05, 'minimum_resolution' : None, 'output_region_size': 50,}
    specs2 = {'fov_y': None, 'fov_x': 90, 'camera_height': 2, 'camera_pitch': -15,
              'rover_pitch': 0, 'rover_roll': 0, 'camera_yaw': 180,
              'desired_resolution': 0.05, 'minimum_resolution' : None, 'output_region_size': 50,}
    specs3 = {'fov_y': None, 'fov_x': 90, 'camera_height': 2, 'camera_pitch': -15,
              'rover_pitch': 0, 'rover_roll': 0, 'camera_yaw': 270,
              'desired_resolution': 0.05, 'minimum_resolution' : None, 'output_region_size': 50,}

    # 4x rover views -> reprojection
    total_image = reproject_multiple_rectilinears_to_aerial(views, [specs0,specs1,specs2,specs3])

    return total_image



def reproject_multiple_rectilinears_to_aerial(images, specs):

    quiet_operation=True

    num_images = len(images)

    total_image = []

    for i in range(num_images):

        # read from array instead of file
        image = images[i]

        image, warped_image = reproject_rectilinear_to_aerial(image, specs[i]['fov_x'], specs[i]['fov_y'],
                                                            specs[i]['camera_height'], specs[i]['camera_pitch'],
                                                            specs[i]['camera_yaw'],specs[i]['rover_pitch'],
                                                            specs[i]['rover_roll'], specs[i]['desired_resolution'],
                                                            specs[i]['minimum_resolution'], specs[i]['output_region_size'], quiet_operation)
        if i == 0:
            total_image = np.array(warped_image)

            midpoint = np.divide(np.subtract(warped_image.shape,1), 2.)
            divider = np.linspace(warped_image.shape[0] - 1, 0, warped_image.shape[0])

            divider0 = np.round(np.array(rotate(np.stack((divider, divider), axis=1), specs[i]['camera_yaw'], midpoint))).astype(int)
            divider1 = np.round(np.array(rotate(np.stack((divider, divider), axis=1), specs[i]['camera_yaw']+90, midpoint))).astype(int)
            divider0 = divider0[int(midpoint[0])-1:]
            divider1 = divider1[int(midpoint[0])-1:]

            image_mask = np.zeros(warped_image.shape, dtype=bool)
            for i in range(len(divider0)):
                image_mask[np.arange(np.min([divider0[i,1], divider1[i,1]]), np.max([divider0[i,1],divider1[i,1]])+1), divider0[i,0]] = True
                image_mask[divider0[i, 1], np.arange(np.min([divider0[i, 0], divider1[i, 0]]), np.max([divider0[i, 0], divider1[i, 0]])+1)] = True
        else:
            warped_image = np.array(warped_image)

            midpoint = np.divide(np.subtract(warped_image.shape,1), 2.)
            divider = np.linspace(warped_image.shape[0] - 1, 0, warped_image.shape[0])

            divider0 = np.round(np.array(rotate(np.stack((divider, divider), axis=1), specs[i]['camera_yaw'], midpoint))).astype(int)
            divider1 = np.round(np.array(rotate(np.stack((divider, divider), axis=1), specs[i]['camera_yaw']+90, midpoint))).astype(int)
            divider0 = divider0[int(midpoint[0])-1:]
            divider1 = divider1[int(midpoint[0])-1:]

            image_mask = np.zeros(warped_image.shape, dtype=bool)
            for i in range(len(divider0)):
                image_mask[np.arange(np.min([divider0[i,1], divider1[i,1]]), np.max([divider0[i,1],divider1[i,1]])+1), divider0[i,0]] = True
                image_mask[divider0[i, 1], np.arange(np.min([divider0[i, 0], divider1[i, 0]]), np.max([divider0[i, 0], divider1[i, 0]])+1)] = True

            total_image[image_mask] = warped_image[image_mask]


    return total_image



def reproject_rectilinear_to_aerial(img, fov_x=90, fov_y=90, camera_height=1, camera_pitch=0, camera_yaw=0, rover_pitch=0,
                                    rover_roll=0, desired_resolution=0.05, minimum_resolution=None, output_region_size=None, quiet_operation=True):
    # Calculate displacement of pixels in first-person perspective for top-down aerial view
    # Outputs:
    #    img: Rectilinear image corrected to remove pixels above horizon (RGB or Greyscale)
    #    warped_img: Aerial image with minimum pixel resolution equal to desired_resolution (RGB or Greyscale)
    # Inputs:
    #    img: Rectilinear image (RGB or Greyscale)
    #    fov_x: Horizontal field of view angles (degrees)
    #    fov_y: Vertical field of view angles (degrees)
    #    camera_y: Height of camera from ground-level (meters)
    #    camera_pitch: Pitch angle of camera. (degrees) 0 = parallel, 90 = zenith, -90 = nadir.
    #    camera_yaw: Yaw angle of camera. (degrees) 0 = North, 90 = East, -90 = West.
    #    rover_pitch: Displacement angle of rover front with respect to tangent (0 horizon)
    #    rover_roll: Displacement angle of rover left side with respect to tangent (0 horizon)
    #    desired_resolution: meteres per pixel

    fov_x_pix_angle, fov_y_pix_angle = calculate_rectilinear_pixel_angle(img, fov_x, fov_y, camera_pitch, quiet_operation)
    img, fov_y_pix_angle = cut_horizon_from_image(img, fov_y_pix_angle, quiet_operation)
    dxdz, dz = calculate_rectilinear_pixel_displacement(fov_x_pix_angle, fov_y_pix_angle, camera_height, quiet_operation)
    dxdz, dz = filter_aerial_resolution(dxdz, dz, minimum_resolution, output_region_size, quiet_operation)
    #dxdz, dz = rotate_pixel_displacements(dxdz, dz, camera_yaw)
    dxdz, dz = rover_aerial_to_satellite_aerial(dxdz, dz, rover_pitch, rover_roll, quiet_operation)
    warped_img = warp_rectilinear_to_aerial(img, dxdz, dz, camera_yaw, desired_resolution, output_region_size, quiet_operation)
    #warped_img = rotate_aerial_image(warped_img, camera_yaw)

    return img, warped_img



def rover_aerial_to_satellite_aerial(dxdz, dz, rover_pitch, rover_roll, quiet_operation=True):
    # Convert pixel displacements from rover top-down to satellite aerial
    # Inputs:
    #    dxdz: x displacement of pixel row, column
    #    dxdz: z displacement of pixel row
    #    rover_pitch: Displacement angle of rover front with respect to tangent (0 horizon)
    #    rover_roll: Displacement angle of rover left side with respect to tangent (0 horizon)
    # Outputs:
    #    dxdz: x displacement of pixel row, column
    #    dxdz: z displacement of pixel row
    if not quiet_operation:
        print('ALERT: Adjusting reprojection to account for rover pitch and roll: '+str(rover_pitch)+', '+str(rover_roll)+' (deg).')

    rover_pitch = (rover_pitch * math.pi) / 180.
    rover_roll = (rover_roll * math.pi) / 180.

    dxdz = np.multiply(dxdz, np.cos(rover_roll))
    dz = np.multiply(dz, np.cos(rover_pitch))
    return dxdz, dz



def warp_rectilinear_to_aerial(img, dxdz, dz, rotation_angle, desired_resolution, output_region_size=None, quiet_operation=True):
    # Convert rectilinear image to aerial view via pixel displacements
    # Inputs:
    #    img: RGB or Greyscale (horizon adjusted)
    #    dxdz: x displacement of pixel row, column (meters)
    #    dxdz: z displacement of pixel row (meters)
    #    desired_resolution: output meter-per-pixel resolution
    # Outputs:
    #    warped_img:

    valid_y = np.where(dz.flatten() != np.inf)
    y_ind = [np.max(valid_y), np.max(valid_y),
             np.min(valid_y), np.min(valid_y)]
    y = [dz[y_ind[0]][0], dz[y_ind[1]][0], dz[y_ind[2]][0], dz[y_ind[3]][0]]

    valid_x = (dxdz != np.inf)
    x_ind = [np.argmax(valid_x[y_ind[0]]), np.max(np.where(valid_x[y_ind[1]])),
             np.argmax(valid_x[y_ind[2]]), np.max(np.where(valid_x[y_ind[3]]))]

    x = [dxdz[y_ind[0], x_ind[0]], dxdz[y_ind[1], x_ind[1]], dxdz[y_ind[2], x_ind[2]],
         dxdz[y_ind[3], x_ind[3]]]

    if output_region_size != None:
        output_resolution = (
            int(np.ceil((np.divide(output_region_size,desired_resolution)))),
            int(np.ceil((np.divide(output_region_size,2*desired_resolution))))) #height is half of width.
        if not quiet_operation:
            print('ALERT: Scaling reprojected tile to fit output region size of: '+str(output_region_size)+' meters for ' + str(desired_resolution) + ' meters per pixel.')
    else:
        output_resolution = (
            # int(np.ceil((np.max(x) - np.min([0., np.min(x)])) / desired_resolution)), int(np.ceil((np.max(y) - np.min([0., np.min(y)])) / desired_resolution)))
            int(np.ceil((np.max(x) - np.min([0., np.min(x)])) / desired_resolution)),
            int(np.ceil((np.max(y) - np.min([0., np.min(y)])) / desired_resolution)))
        if not quiet_operation:
            print('ALERT: Scaling reprojected tile for desired resolution of: ' + str(desired_resolution) + ' meters per pixel.')

    square_resolution = np.max([np.max(output_resolution), np.min(output_resolution) * 2])

    x = np.subtract(x, np.min([0, np.min(x)]))
    x = np.divide(x, np.max(x))
    x = np.multiply(x, output_resolution[0])
    y = np.subtract(y, np.min([0, np.min(y)]))
    y = np.divide(y, np.max(y))
    y = np.multiply(y, output_resolution[1])
    y = np.subtract(square_resolution/2, y)
    if not quiet_operation:
        print('ALERT: Rotating output reprojection points by camera yaw of ' + str(rotation_angle) + ' (deg)')
    new_points = np.array(rotate(np.stack((x, y), axis=1), rotation_angle, (square_resolution/2, square_resolution/2)))
    x = new_points[:, 0]
    y = new_points[:, 1]

    if not quiet_operation:
        print('ALERT: Warping first-perspective to aerial reprojection.')
    # close left close right far left far right
    pts1 = np.float32([[x_ind[0], y_ind[0]], [x_ind[1], y_ind[1]], [x_ind[2], y_ind[2]],
                       [x_ind[3], y_ind[3]]])  # 0,0 is top left (above horizon)
    pts2 = np.float32([[x[0], y[0]], [x[1], y[1]], [x[2], y[2]], [x[3], y[3]]])


    M = cv.getPerspectiveTransform(pts1.astype('float32'), pts2.astype('float32'))

    try:
        warped_img = cv.warpPerspective(img, M, (square_resolution, square_resolution))
    except:
        print('ERROR: Something went wrong during reprojection! Warping terminated.')
        warped_img = None

    return warped_img



def filter_aerial_resolution(dxdz, dz, minimum_resolution=None, output_region_size =None, quiet_operation=True):
    # Filter regions that do not meet upper bound of resolution
    # Outputs:
    #    img: RGB or Greyscale
    #    dxdz: x displacement of pixel row, column
    #    dxdz: z displacement of pixel row
    # Inputs:
    #    img: RGB or Greyscale
    #    dxdz: x displacement of pixel row, column
    #    dxdz: z displacement of pixel row
    #    desired_resolution: metres per pixel

    if output_region_size != None:
        if not quiet_operation:
            print('ALERT: Limiting reprojection tile to output region size: '+str(output_region_size)+' square meters.')
            print('WARNING: Minimum resolution parameter is being ignored.')
        dz[dz > (output_region_size/2.)] = np.inf
        dxdz[np.abs(dxdz) > (output_region_size/2.)] = np.inf
    elif minimum_resolution != None:
        if not quiet_operation:
            print('ALERT: Filtering reprojection tile to represent pixels of minimum resolution: ' + str(minimum_resolution) + ' meters.')
        ddz = dz[1:] - dz[0:-1]
        dz[np.where(np.abs(ddz) > minimum_resolution)[0]] = np.inf
        ddxdz = dxdz[:, 1:] - dxdz[:, 0:-1]
        mid_dx = int(np.floor(dxdz.shape[1] / 2))
        dxdz_nans = np.array(np.where(ddxdz > minimum_resolution))
        dxdz_nans[1, np.where(dxdz_nans[1] > mid_dx)] += 1
        dxdz[dxdz_nans[0], dxdz_nans[1]] = np.inf
    else:
        if not quiet_operation:
            print('ALERT: No filtering on minimum input resolution or limiting of output region size.')
            print('WARNING: Distance to horizon is '+str(dz[-1])+'meters. Output image may be very large.')

    return dxdz, dz



def cut_horizon_from_image(img, fov_y_pix_angle, quiet_operation=True):
    if not quiet_operation:
        print('ALERT: Removing pixels above horizon from image.')
    horizon_point = np.min(np.where(fov_y_pix_angle <= 0)[0])
    fov_y_pix_angle = fov_y_pix_angle[horizon_point:]
    img = img[horizon_point:, :]
    return img, fov_y_pix_angle



def calculate_rectilinear_pixel_displacement(fov_x_pix_angle, fov_y_pix_angle, camera_height, quiet_operation=True):
    if not quiet_operation:
        print('ALERT: Calculating ground-plane pixel displacement from field of view radians-per-pixel and a camera height of '+str(camera_height)+' meters.')
    dz = np.multiply(float(camera_height), np.tan(fov_y_pix_angle + (math.pi / 2)))
    # calculates the distance of each horizontal line in the FOV image
    # assuming a flat plane parallel to the base of the rover

    dz2 = np.sqrt(np.add(np.power(dz, 2), np.power(camera_height, 2)))
    dxdz = np.dot(dz2, np.tan(fov_x_pix_angle))

    return dxdz, dz



def calculate_rectilinear_pixel_angle(img, fov_x, fov_y, camera_pitch, quiet_operation=True):
    # Calculate displacement of pixels in first-person perspective for top-down aerial view
    # Outputs:
    #    img: RGB or Greyscale
    #    dxdz: x displacement of pixel row, column
    #    dxdz: z displacement of pixel row
    # Inputs:
    #    img: RGB or Greyscale
    #    fov_x: Horizontal field of view angles (degrees)
    #    fov_y: Vertical field of view angles (degrees)
    #    camera_y: Height of camera from ground-level (meters)
    #    camera_pitch: Pitch angle of camera. (degrees) 0 = parallel, 90 = zenith, -90 = nadir.

    if not quiet_operation:
        print('ALERT: Calculating radians-per-pixel of horizontal and vertical fields of view: '+str(fov_x)+','+str(fov_y)+' (deg), for camera pitch: '+str(camera_pitch)+' (deg).')
    fov_height, fov_width = img.shape[:2]

    if fov_x == None:
        fov_x = 90.
    fov_x = (fov_x * math.pi) / 180.
    if fov_y == None:
        fov_y = 2 * np.arctan((float(fov_height) / float(fov_width)) * np.tan(fov_x / 2))
        # fov_y = (float(fov_height)/float(fov_width))*float(fov_x)
    else:
        fov_y = (fov_y * math.pi) / 180.

    camera_pitch = (camera_pitch * math.pi) / 180.

    rad_per_pix_y = float(fov_y) / float(fov_height)
    rad_per_pix_x = float(fov_x) / float(fov_width)

    fov_y_pix_angle = np.zeros([int(fov_height), 1])
    fov_y_pix_angle[:, 0] = np.add(
        np.subtract(np.multiply(np.linspace(fov_height - 0.5, 0.5, fov_height), rad_per_pix_y), (fov_y / 2)),
        camera_pitch)
    fov_x_pix_angle = np.zeros([1, fov_width])
    fov_x_pix_angle[0, :] = np.subtract(np.multiply(np.linspace(0.5, fov_width - 0.5, fov_width), rad_per_pix_x),
                                        (fov_x / 2))
    return fov_x_pix_angle, fov_y_pix_angle



def join(iterator, seperator):
    it = map(str, iterator)
    seperator = str(seperator)
    string = next(it, '')
    for s in it:
        string += seperator + s
    return string



def make_rotation_transformation(angle, origin=(0, 0)):
    cos_theta, sin_theta = np.cos(angle), np.sin(angle)
    x0, y0 = origin
    def xform(point):
        x, y = point[0] - x0, point[1] - y0
        return (x * cos_theta - y * sin_theta + x0,
                x * sin_theta + y * cos_theta + y0)
    return xform



def rotate(points, angle, anchor=(0, 0)):
    angle = (angle / 180.)*np.pi
    xform = make_rotation_transformation(angle, anchor)
    return [xform(p) for p in points]



##### END FDL REPROJECTION SCRIPT



# parse tensorflow example
def _input_parser(example):

    features = {
        'height': tf.io.FixedLenFeature((), tf.int64),
        'width': tf.io.FixedLenFeature((), tf.int64),
        'offset_y': tf.io.FixedLenFeature((), tf.float32),
        'offset_x': tf.io.FixedLenFeature((), tf.float32),
        'match': tf.io.FixedLenFeature((), tf.int64),
        'iou': tf.io.FixedLenFeature((), tf.float32),
        'tile1_raw': tf.io.FixedLenFeature((), tf.string),
        'tile2_raw': tf.io.FixedLenFeature((), tf.string)
    }

    parsed_example = tf.io.parse_single_example(example, features)

    width = parsed_example['width']
    height = parsed_example['height']

    tile1_img = tf.io.decode_raw(parsed_example['tile1_raw'], tf.float64)
    tile2_img = tf.io.decode_raw(parsed_example['tile2_raw'], tf.float64)

    match = parsed_example['match']
    offset_x = parsed_example['offset_x']
    offset_y = parsed_example['offset_y']

    return { "tile1_img": tile1_img,
             "tile2_img": tile2_img,
             "width": width,
             "height": height}, \
                {   'match': match,
                    'offset_x': offset_x,
                    'offset_y': offset_y
                }



class gui(tk.Tk):

    def __init__(self, parent, *args, **kwargs):

        tk.Frame.__init__(self, parent, *args, **kwargs)

        self.parent = parent

        self.masterframe = tk.Frame(self.parent)
        self.masterframe.grid()

        self.panelCam0 = None
        self.panelCam90 = None
        self.panelCam180 = None
        self.panelCam270 = None
        self.panelCamRep = None

        self.panelTFRep = None
        self.panelTFSat = None

        self.panelMatch = None
        self.panelPrediction = None

        self.cam_img = [None, None, None, None]

        self.reprojection = None
        self.tf_reprojection = None
        self.tf_satellite = None

        self.cam_threads = []
        self.rep_thread = None

        self.match = "Dataset: Not Available"
        self.prediction = "Prediction: Not Available"

        return



    def run_capture(self):

        self.cam_threads.append(threading.Thread(target=self.capture_location))
        self.cam_threads[len(self.cam_threads)-1].start()

        return



    def capture_location(self):

        camera_connected = True

        # initialize camera array
        cv_img = [None, None, None, None]

        # gather stepper controller status
        try:
            status = yaml.load(ticcmd('-s', '--full'))
            if status['Operation state'] != 'Normal':
                print('ERROR: Stepper controller is not operating correctly. State: ' + status['Operation State'] + ', Voltage: ' + status['VIN voltage'])
                return
            position = status['Current position']
        except:
            camera_connected = False


        for i in range(4):

            timeout_length = 3 # 3 second timeout period
            sleep_length = 0.1 # poll stepper every 0.1s

            if camera_connected:
                # rotate stepper controller to appropriate camera position
                ticcmd('--exit-safe-start', '--position', str(200 * i))
                status = yaml.load(ticcmd('-s', '--full'))
                position = status['Current position']


                while position != (200 * i) and timeout_length > 0:
                    time.sleep(sleep_length)
                    status = yaml.load(ticcmd('-s', '--full'))
                    position = status['Current position']
                    timout_length = timeout_length - sleep_length

                # handle timout condition
                if timeout_length <= 0:
                    print('ERROR: Stepper controller failed to assume the provided position.')
                    return
            else:
                time.sleep(1)

            # capture image
            cam = cv.VideoCapture(CAMERA_DEVICE_NUMBER)
            ret, img = cam.read()
            cam.release()

            # convert to grayscale
            cv_img[i] = cv.cvtColor(img, cv.COLOR_BGR2GRAY)

            ### post process
            # convert to PIL
            self.cam_img[i] = Image.fromarray(cv_img[i])

            # resize for interface
            self.cam_img[i] = self.cam_img[i].resize((380, 214), Image.ANTIALIAS)

            # convert to ImageTk
            self.cam_img[i] = ImageTk.PhotoImage(self.cam_img[i])

        if camera_connected:
            # reset servo position
            ticcmd('--exit-safe-start', '--position', str(0))

        # generate reprojection
        self.reprojection = reproj_fn(cv_img)
        self.reprojection = Image.fromarray(self.reprojection)
        self.reprojection = self.reprojection.resize((448, 448), Image.NEAREST)
        self.reprojection = ImageTk.PhotoImage(self.reprojection)

        self.update_camera_images()

        return



    def update_camera_images(self):

        # create interface
        if self.panelCam0 is None or self.panelCam90 is None or self.panelCam180 is None or self.panelCam270 is None:

            self.panelCam0 = tk.Label(self.masterframe, image=self.cam_img[0])
            self.panelCam0.image = self.cam_img[0]
            self.panelCam0.grid(in_=self.masterframe, row=0, column=0, padx=10, pady=10, sticky='nw')

            self.panelCam90 = tk.Label(self.masterframe, image=self.cam_img[1])
            self.panelCam90.image = self.cam_img[1]
            self.panelCam90.grid(in_=self.masterframe, row=0, column=1, padx=10, pady=10, sticky='nw')

            self.panelCam180 = tk.Label(self.masterframe, image=self.cam_img[2])
            self.panelCam180.image = self.cam_img[2]
            self.panelCam180.grid(in_=self.masterframe, row=1, column=0, padx=10, pady=10, sticky='nw')

            self.panelCam270 = tk.Label(self.masterframe, image=self.cam_img[3])
            self.panelCam270.image = self.cam_img[3]
            self.panelCam270.grid(in_=self.masterframe, row=1, column=1, padx=10, pady=10, sticky='nw')

            self.panelCamRep = tk.Label(self.masterframe, image=self.reprojection)
            self.panelCamRep.image = self.reprojection
            self.panelCamRep.grid(in_=self.masterframe, row=0, column=2, rowspan=2, padx=10, pady=10, sticky='ne')

            button = tk.Button(self.masterframe, text="Capture Location", command=self.run_capture)
            button.grid(in_=self.masterframe, row=2, column=2, padx=10, pady=10, sticky='ne')

        else:
            # update the panels
            self.panelCam0.configure(image=self.cam_img[0])
            self.panelCam90.configure(image=self.cam_img[1])
            self.panelCam180.configure(image=self.cam_img[2])
            self.panelCam270.configure(image=self.cam_img[3])
            self.panelCamRep.configure(image=self.reprojection)
            self.panelCam0.image = self.cam_img[0]
            self.panelCam90.image = self.cam_img[1]
            self.panelCam180.image = self.cam_img[2]
            self.panelCam270.image = self.cam_img[3]
            self.panelCamRep.image = self.reprojection

        return



    def run_reprojection(self):

        self.rep_thread = threading.Thread(target=self.process_reprojection)
        self.rep_thread.start()

        return



    def process_reprojection(self):

        global PREDICT_BATCH_SIZE, ARGS

        images = None

        ### START REPROJECTION MATCHING

        # create Inference Engine, load Intermediate Representation
        ie = IECore()
        net = IENetwork(model=MODEL_XML, weights=MODEL_BIN)

        # check for unsupported layers in model with respect to the chosen device
        if "MYRIAD" in ARGS.device:
            supported_layers = ie.query_network(net, "MYRIAD")
            not_supported_layers = [l for l in net.layers.keys() if l not in supported_layers]
            if len(not_supported_layers) != 0:
                log.error("Following layers are not supported by the plugin for specified device {}:\n {}".
                          format(ARGS.device, ', '.join(not_supported_layers)))
        elif "CPU" in ARGS.device:
            supported_layers = ie.query_network(net, "CPU")
            not_supported_layers = [l for l in net.layers.keys() if l not in supported_layers]
            if len(not_supported_layers) != 0:
                log.error("Following layers are not supported by the plugin for specified device {}:\n {}".
                          format(ARGS.device, ', '.join(not_supported_layers)))

        # create blobs for inference input_output
        input_blob = next(iter(net.inputs))
        output_blob = next(iter(net.outputs))

        # load tensorflow record
        predict_dataset = tf.data.TFRecordDataset(PREDICT_DATASET)

        predict_dataset = predict_dataset.map(_input_parser)
        predict_dataset = predict_dataset.batch(PREDICT_BATCH_SIZE)
        iterator = tf.compat.v1.data.make_one_shot_iterator(predict_dataset)

        features, labels = iterator.get_next()

        # load network to movidius device
        exec_net = ie.load_network(network=net, device_name=ARGS.device)

        with tf.compat.v1.Session() as sess:

            sess.run(tf.compat.v1.global_variables_initializer())

            try:
                while True:
                    image, metadata = sess.run([features, labels])

                    tile1_src = image["tile1_img"]
                    tile2_src = image["tile2_img"]

                    tile1_src = tf.reshape(tile1_src, (-1, INPUT_HEIGHT, INPUT_WIDTH))
                    tile2_src = tf.reshape(tile2_src, (-1, INPUT_HEIGHT, INPUT_WIDTH))

                    tile1_stacked = tf.stack((tile1_src, tile1_src, tile1_src), axis=1)
                    tile2_stacked = tf.stack((tile2_src, tile2_src, tile2_src), axis=1)

                    tile1_image = tf.cast(tile1_src*255, tf.uint8)
                    tile2_image = tf.cast(tile2_src*255, tf.uint8)

                    self.tf_reprojection = Image.fromarray(tile1_image[0].eval())
                    self.tf_reprojection = self.tf_reprojection.resize((448, 448), Image.NEAREST)
                    self.tf_reprojection = ImageTk.PhotoImage(image=self.tf_reprojection)

                    self.tf_satellite = Image.fromarray(tile2_image[0].eval())
                    self.tf_satellite = self.tf_satellite.resize((448, 448), Image.NEAREST)
                    self.tf_satellite = ImageTk.PhotoImage(image=self.tf_satellite)

                    # extract feature vectors from MYRIAD device
                    res1 = exec_net.infer(inputs={input_blob: tile1_stacked.eval()})
                    res2 = exec_net.infer(inputs={input_blob: tile2_stacked.eval()})

                    if metadata['match']:
                        self.match = "Dataset: Match"
                    else:
                        self.match = "Dataset: No Match"

                    self.update_tf_images()
                    time.sleep(3)




            except tf.errors.OutOfRangeError:
                 pass

        # n, c, h, w = net.inputs[input_blob].shape
        # images = np.ndarray(shape=(n, c, h, w))


        #combined_feature_map = tf.stack([tile1_feature_maps, tile2_feature_maps],axis=1)
        #combined_feature_map_flat = tf.reshape(combined_feature_map, [-1, 2 * 2048])


        #label = tf.cast(features['train/label'], tf.int32)


        # for i in range(n):
        #     tile1_image = tf.cast(predict_dataset["tile1_img"], tf.float32)
        #
        #
        # res = exec_net.infer(inputs={input_blob: images})
        # res = res[output_blob]

        ### END REPROJECTION MATCHING

        # Create the Estimator
        # deep_matcher = tf.estimator.Estimator(model_fn=cnn_model_fn, model_dir="ovmodels/")

        # predictions = deep_matcher.predict(
        #     input_fn=predict_dataset_input_fn)
        # for prediction in predictions:
        #     print(prediction)

        # self.update_tf_images()

        return



    def update_tf_images(self):

        if self.panelTFRep is None or self.panelTFSat is None:

            self.panelTFRep = tk.Label(self.masterframe, image=self.tf_reprojection)
            self.panelTFRep.image = self.tf_reprojection
            self.panelTFRep.grid(in_=self.masterframe, row=2, rowspan=2, column=0, padx=10, pady=10)

            self.panelTFSat = tk.Label(self.masterframe, image=self.tf_satellite)
            self.panelTFSat.image = self.tf_satellite
            self.panelTFSat.grid(in_=self.masterframe, row=2, rowspan=2, column=1, padx=10, pady=10)

            self.panelMatch = tk.Label(self.masterframe, text=self.match)
            self.panelMatch.grid(in_=self.masterframe, row=2, column=2, padx=10, pady=10, sticky='sw')

            self.panelPrediction = tk.Label(self.masterframe, text=self.prediction)
            self.panelPrediction.grid(in_=self.masterframe, row=3, column=2, padx=10, pady=10, sticky='nw')

        else:

            self.panelTFRep.configure(image=self.tf_reprojection)
            self.panelTFRep.image = self.tf_reprojection

            self.panelTFSat.configure(image=self.tf_satellite)
            self.panelTFSat.image = self.tf_satellite

            self.panelMatch.configure(text=self.match)
            self.panelPrediction.configure(text=self.prediction)


        return



def main():

    global ARGS

    # parse arguments
    ARGS = build_argparser().parse_args()

    root = tk.Tk()
    root.title("Lunar Localization Program")
    main_gui = gui(root)

    main_gui.run_capture()
    main_gui.run_reprojection()

    ### display interface
    root.mainloop()

    return



if __name__ == "__main__":
    sys.exit(main() or 0)
#    tf.compat.v1.app.run()