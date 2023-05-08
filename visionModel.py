import cv2
import time
from google.auth.credentials import Credentials
import io
import os

# Imports the Google Cloud client library
from google.cloud import vision

import json
from google.oauth2 import service_account

def visionMain(pipe):
    keyfile_dict = json.loads(open('baraboo.json').read())
    credentials = service_account.Credentials.from_service_account_info(keyfile_dict)

    # Instantiates a client
    client = vision.ImageAnnotatorClient(credentials=credentials)

    alpha = 1.2  # Contrast control (1 - 3)
    beta = 10  # Brightness control (0 - 100)
    save = True # display the camera view


    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        print("Vision: Error opening video capture device")
        quit()
    count = 0

    while True:
        ret, frame = camera.read()
        frame = cv2.convertScaleAbs(frame, alpha=alpha, beta=beta)
        cv2.imshow("Camera View", frame)
        key = cv2.waitKey(1)
        if pipe.poll():
            cmd = pipe.recv()
        else:
            cmd = None

        if cmd == "Capture":  # "return" takes a snapshot
            print(f"Vision: Taking snapshot")
            if save:
                filename = f"snapshot_{count}.jpg"
                cv2.imwrite(filename, frame) # save the snapshot to file
            count += 1 # keep count of snapshots
            time.sleep(1) # pause the camera view for 1 second

            # Loads the image into memory
            with io.open(filename, 'rb') as image_file:
                content = image_file.read()

            image = vision.Image(content=content)

            # Performs label detection on the image file
            response = client.object_localization(image=image)
            labels = response.localized_object_annotations

            pipe.send([label.name for label in labels])

        elif cmd == "Exit":
            print("Vision: Exiting vision process")
            return

    camera.release()
    cv2.destroyAllWindows()
