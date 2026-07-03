import time

target_detected = False
target_center = None  # (x, y)
target_bbox = None  # (x, y, w, h)
target_metrics = None  # {'bbox_area_ratio': float, 'blue_ratio': float, ...}
depth_global_metrics = None  # {'full_frame_blue_ratio': float, 'mid_threshold_m': float, ...}
frame_dimensions = None  # (width, height)
autopilot_active = False
autopilot_status = "Inactiv"
edge_distances = None  # (left_distance, right_distance)
edge_distances_timestamp = None  # Unix timestamp for latest depth sample used in edge_distances
wall_measurements = {}  # {'front': float, 'left': float, 'right': float}
measurement_log = []  # [{'wall': str, 'distance': float|None, 'timestamp': float, 'source': str}]
room_timeline = {}  # {room_index: 'pending'|'entered'|'exited'}
current_room_index = None

# ---- Stair Climber States ----
stair_metrics = None
stair_frame_da2 = None
stair_frame_sobel = None
stair_frame_gabor = None


def init_room_timeline(room_count):
    global room_timeline, current_room_index
    count = max(1, int(room_count))
    room_timeline = {idx: "pending" for idx in range(1, count + 1)}
    current_room_index = None


def set_current_room(room_index):
    global current_room_index
    if room_index is None:
        current_room_index = None
        return

    idx = int(room_index)
    current_room_index = idx
    if idx not in room_timeline:
        room_timeline[idx] = "pending"


def _set_room_timeline_state(room_index, new_state):
    if room_index is None:
        return

    idx = int(room_index)
    if idx not in room_timeline:
        room_timeline[idx] = "pending"

    rank = {"pending": 0, "entered": 1, "exited": 2}
    current_state = room_timeline.get(idx, "pending")
    if rank.get(new_state, 0) >= rank.get(current_state, 0):
        room_timeline[idx] = new_state


def mark_room_entered(room_index=None):
    _set_room_timeline_state(room_index if room_index is not None else current_room_index, "entered")


def mark_room_exited(room_index=None):
    _set_room_timeline_state(room_index if room_index is not None else current_room_index, "exited")

def set_edge_distances(left_distance, right_distance, sample_timestamp=None):
    global edge_distances, edge_distances_timestamp
    edge_distances = (left_distance, right_distance)
    edge_distances_timestamp = (
        float(sample_timestamp) if sample_timestamp is not None else time.time()
    )

def log_wall_measurement(wall, distance, source="phase3"):
    measurement_log.append(
        {
            "wall": wall,
            "distance": float(distance) if distance is not None else None,
            "timestamp": time.time(),
            "source": source,
        }
    )

def set_target_detection(detected, center=None, bbox=None, dimensions=None, metrics=None):
    global target_detected, target_center, target_bbox, target_metrics, frame_dimensions
    target_detected = detected
    if detected:
        target_center = center
        target_bbox = bbox
        target_metrics = dict(metrics or {})
        frame_dimensions = dimensions


def set_depth_global_metrics(metrics=None):
    global depth_global_metrics
    depth_global_metrics = dict(metrics or {})

def get_navigation_status():
    return {
        "target_detected": target_detected,
        "target_center": target_center,
        "target_bbox": target_bbox,
        "target_metrics": target_metrics,
        "depth_global_metrics": depth_global_metrics,
        "frame_dimensions": frame_dimensions,
        "edge_distances": edge_distances,
        "edge_distances_timestamp": edge_distances_timestamp,
        "autopilot_active": autopilot_active,
        "autopilot_status": autopilot_status,
        "wall_measurements": wall_measurements,
        "measurement_log": measurement_log,
        "room_timeline": room_timeline,
        "current_room_index": current_room_index,
        "stair_metrics": stair_metrics,
    }

def reset_navigation_state():
    global target_detected, target_center, target_bbox, target_metrics, depth_global_metrics, frame_dimensions
    global autopilot_active, autopilot_status, edge_distances, edge_distances_timestamp, wall_measurements, measurement_log
    global room_timeline, current_room_index
    global stair_metrics, stair_frame_da2, stair_frame_sobel, stair_frame_gabor

    target_detected = False
    target_center = None
    target_bbox = None
    target_metrics = None
    depth_global_metrics = None
    frame_dimensions = None
    autopilot_active = False
    autopilot_status = "Inactiv"
    edge_distances = None
    edge_distances_timestamp = None
    wall_measurements = {}
    measurement_log = []
    room_timeline = {}
    current_room_index = None
    
    stair_metrics = None
    stair_frame_da2 = None
    stair_frame_sobel = None
    stair_frame_gabor = None
