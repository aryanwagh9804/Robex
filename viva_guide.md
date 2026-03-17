# 🤖 ROBEX - FINAL PROJECT GUIDE & VIVA REPORT

This document acts as your **Complete Explanation Guide** for teachers and project guides. It covers *what* the system does, *how* it does it, the algorithms used, and how it was designed securely.

---

## 🔬 1. THE CORE ALGORITHMS (The Brains)

When the camera looks at a person or an object, **4 distinct Artificial Intelligence algorithms** execute simultaneously to make decisions.

### 👥 A. Face Detection: **Haar Cascade**
*   **What it is**: A fast, lightweight machine-learning object detection algorithm.
*   **How it works**: It scans the image frame looking for dark and light contrast intervals that look like "Eyes", "Nose", and "Mouth".
*   **Why we use it**: It is extremely fast and lets the computer draw the yellow boundary box instantly without lagged processing.
*   **🛠️ How it looks in our Code**:
    ```python
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.3, 5)
    ```
    *   `cvtColor`: Converts frame to grayscale because colors aren't needed for face shape detection (saves CPU).
    *   `detectMultiScale`: Scales the image layer by layer to find faces both close and far. `1.3` is expansion scale, `5` is strict neighbors threshold to eliminate fake boxes.

### 🎓 B. Face Recognition: **LBPH** (*Local Binary Patterns Histograms*)
*   **What it is**: A texture-based classification algorithm.
*   **How it works**: 
    1. It breaks the face bounding box into small grids.
    2. It compares every pixel to its 8 neighbors. If a neighbor is brighter, it is assigned a `1`. If darker, it gets a `0`.
    3. It builds a **texture map** (histogram graph) unique to that student and compares it against the database vectors for a match.
*   **Why we use it**: It is highly accurate even if lighting or mood changes, and requires low processor computation to predict correctly.
*   **🛠️ How it looks in our Code**:
    ```python
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    id_pred, confidence = recognizer.predict(face_resized)
    ```
    *   `predict()`: Returns the closest matched ID from our SQLite tables.
    *   **Confidence**: Stands for "Distance value". Lower confidence scores mean the image is a **closer match** to the model database.

### 📱 C. Anti-Spoofing / Object Detection: **YOLOv8**
*   **What it is**: A deep neural network built for high-speed object categorization.
*   **How it works**: It looks at the whole frame just **once**, runs it through neural weights, and outputs bounding boxes labeled `"person"`, `"cell phone"`, `"remote"`, etc.
*   **Why we use it**: It prevents fake attendance tricks (holding up a phone displaying a picture) instantly.
*   **🛠️ How it looks in our Code**:
    ```python
    results = yolo_model(frame, verbose=False)
    for box in results[0].boxes:
        cls_id = int(box.cls[0])
        label = yolo_model.names[cls_id]
    ```
    *   `yolo_model()`: Processes the frame to predict modern visual indices.
    *   `box.cls`: Loads the exact identified category (e.g., cell phone = code index 67).

### 👁️ D. Liveness Detection: **Dlib EAR** (*Eye Aspect Ratio*)
*   **What it is**: A geometric landmark tracker.
*   **How it works**: It maps 68 invisible dots onto the face shape making up eyes, brows, and jaw. It tracks the distance between the upper and lower eyelid. If the ratio drops temporarily, it knows the student **blinked**—confirming a living human dashboard.
*   **🛠️ How it looks in our Code**:
    ```python
    rects = detector(gray, 0)
    shape = predictor(gray, rect)
    leftEye = shape[42:48] # Extracts eye coords
    ear = (dist(p2, p6) + dist(p3, p5)) / (2 * dist(p1, p4))
    ```
    *   We map 6 points for each eye. 
    *   It calculates **Vertical height divided by Horizontal length**. When your eye closes, the vertical becomes 0, lowering the equation score proving a **Blink**.

---

## 🔄 2. THE SYSTEM DATA FLOW (The Path)

To avoid saying "It just works", explain the connection pipeline in 4 stages:

1.  **Capture Stage**: The ESP32-CAM captures raw CMOS sensor pictures and converts them into `.jpg` arrays (10-15 per second).
2.  **Streaming Stage**: The ESP32 pushes these bytes onto a local server buffer via **Wi-Fi** using an HTTP stream address (`http://esp32-ip/stream`).
3.  **Analytics Stage (Laptop Server)**:
    *   Laptop receives the frames.
    *   First, passes through YOLOv8 to double-check for laptops/phones.
    *   Second, passes through Dlib to test for Eye-Blinking.
    *   Finally, triggers the LBPH algorithm to predict the person's identity.
4.  **Logging Stage**: If correctly identified, it contacts the **Google Sheets API** and pushes a row: `[Name, Date, Subject, Time, Status]`.

---

## 💻 3. EDGE COMPUTING (Why use a laptop, not the cloud?)

Your guide will ask: *"Why didn't you deploy the server on Amazon AWS or Google Cloud?"*

*   **The Answer**: We are using **Edge Computing** (Local processing).
*   **Why this is better for Robotics**:
    1.  **Latency (Speed)**: Streaming live video up to the internet cloud takes 2-4 seconds of lagging buffer. By processing on the laptop, response is instant (<1.2 seconds).
    2.  **Bandwidth Costs**: Uploading continuous video over the internet uses Gigabytes of data traffic. 
    3.  **Safety from disconnects**: If the internet goes down, the robot doesn’t crash or stop functioning; it continues recording the database.

---

## 🛰️ 4. ESP32 FIRMWARE LOGIC (How it Communicates)

The ESP32 is a **Microcontroller**, not a full computer. It works by playing requests with the Laptop server every **300ms** inside a continuous loop:

1.  **Boot Phase**: Connects to the local classroom Wi-Fi router. Sets pins output for Motors and I2S speaker streams.
2.  **Streaming Phase**: Starts the web server port listening hook allowing the laptop to pull frames.
3.  **The Polling Loop**: 
    *   Every **300ms**, the ESP32 asks the laptop: `"What is the current state?"`
    *   The laptop responds with directions: `[Move: Forward, Stop, Play Audio: "Aryan Present"]`.
4.  **Audio Subsystem**: If the response is audio, the ESP32 triggers an `HTTP GET` streaming read downloading sound buffers which the **MAX98357A Amplifer** pushes into the physical speaker.

---

## 🛡️ 5. DATA SECURITY LOCKDOWN (The SQLite framework upgrade)

Previously, images were saved in folders. To secure the system from guide critiques regarding file-tampering, we upgraded to **SQLite DB Security**:

*   **What we did**: Migrated folder images into a compiled byte-matrix Database file (`dataset.db`).
*   **How it secures data**:
    1.  Regular users **cannot open or rename** pictures inside folder trees.
    2.  Student photos are compressed into **BLOB (Binary Large Object)** data structures inside secured SQL containers.
    3.  It prevents accidental deletes and saves database integrity from mid-air power crashes using ACID-compliant rollbacks.

---
