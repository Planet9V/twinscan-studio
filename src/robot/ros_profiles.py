"""Authoritative ROS 1 Noetic vs. ROS 2 Humble profiles and message/service wiring for PuppyPi Pro.

Encapsulates exact verified container paths, ROSBridge v2 message/service type names,
camera topics, SLAM/navigation stacks, and lifecycle metadata audited on PuppyPi Pro.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

ROS_PROFILES: Dict[str, Dict[str, Any]] = {
    "ros1": {
        "id": "ros1",
        "name": "ROS 1 Noetic",
        "distro": "noetic",
        "display_label": "ROS 1 Noetic Ninjemys",
        "container_name": "puppypi",
        "ubuntu_version": "Ubuntu 20.04 LTS (Focal)",
        "middleware": "rosmaster XML-RPC (:11311) + TCPROS",
        "rmw_implementation": "roscpp / rospy (TCPROS)",
        "domain_id": None,
        "support_status": "EOL (May 2025)",
        "is_eol": True,
        "eol_date": "2025-05-31",
        "slam_stack": "gmapping / hector_slam / karto",
        "nav_stack": "move_base + teb_local_planner",
        "manipulation_stack": "ActionGroups (.d6ac / .d6a) + direct servo PWM",
        "camera_topic": "/usb_cam/image_raw",
        "camera_topics": [
            "/usb_cam/image_raw",
            "/apriltag_detect/image_result",
            "/color_detect/image_result",
            "/face_detect/image_result",
            "/object_tracking/image_result",
            "/visual_patrol/image_result",
            "/lab_config_manager/image_result",
        ],
        "puppy_py_path": "/home/ubuntu/puppypi/src/puppy_control/scripts/puppy.py",
        "puppy_py_fallbacks": [
            "/home/ubuntu/puppypi/src/puppy_control/scripts/puppy.py",
            "/home/ubuntu/ros_ws/src/puppy_control/scripts/puppy.py",
        ],
        "env_file_path": "/home/ubuntu/puppypi/.robotrc",
        "default_with_arm": 0,
        "theme_accent": "sky",
        "message_types": {
            "velocity": "puppy_control/Velocity",
            "pose": "puppy_control/Pose",
            "gait": "puppy_control/Gait",
            "servo": "puppy_control/SetServo",
            "buzzer": "ros_robot_controller/BuzzerState",
            "rgb": "ros_robot_controller/RGBsState",
            "oled": "ros_robot_controller/OLEDState",
            "battery": "std_msgs/UInt16",
            "imu": "sensor_msgs/Imu",
            "scan": "sensor_msgs/LaserScan",
        },
        "service_types": {
            "run_action": "puppy_control/SetRunActionName",
            "go_home": "std_srvs/Empty",
            "set_bool": "std_srvs/SetBool",
        },
        "highlights": [
            "Autostarts automatically via start_node.service",
            "Full Hiwonder app suite (AprilTag, Face, Color, Visual Patrol)",
            "Legacy rosmaster (:11311) — End-of-Life since May 2025",
        ],
    },
    "ros2": {
        "id": "ros2",
        "name": "ROS 2 Humble",
        "distro": "humble",
        "display_label": "ROS 2 Humble Hawksbill",
        "container_name": "puppypi_ros2",
        "ubuntu_version": "Ubuntu 22.04 LTS (Jammy)",
        "middleware": "DDS (rmw_cyclonedds_cpp, ROS_DOMAIN_ID=0)",
        "rmw_implementation": "rmw_cyclonedds_cpp",
        "domain_id": 0,
        "support_status": "LTS Active (through May 2027)",
        "is_eol": False,
        "eol_date": "2027-05-31",
        "slam_stack": "slam_toolbox 2.6.8 + rf2o_laser_odometry",
        "nav_stack": "Nav2 1.1.16 + teb_local_planner",
        "manipulation_stack": "MoveIt 2.5.5 + puppy_control_msgs + ActionGroups",
        "camera_topic": "/image_raw",
        "camera_topics": [
            "/image_raw",
            "/usb_cam/image_raw",
            "/apriltag_detect/image_result",
            "/color_detect/image_result",
            "/face_detect/image_result",
            "/object_tracking/image_result",
        ],
        "puppy_py_path": "/home/ubuntu/ros2_ws/src/driver/puppy_control/puppy_control/puppy.py",
        "puppy_py_fallbacks": [
            "/home/ubuntu/ros2_ws/src/driver/puppy_control/puppy_control/puppy.py",
        ],
        "env_file_path": "/home/ubuntu/ros2_ws/.typerc",
        "default_with_arm": 1,
        "theme_accent": "orange",
        "message_types": {
            "velocity": "puppy_control_msgs/msg/Velocity",
            "pose": "puppy_control_msgs/msg/Pose",
            "gait": "puppy_control_msgs/msg/Gait",
            "servo": "puppy_control_msgs/msg/SetServo",
            "buzzer": "ros_robot_controller_msgs/msg/BuzzerState",
            "rgb": "ros_robot_controller_msgs/msg/RGBsState",
            "oled": "ros_robot_controller_msgs/msg/OLEDState",
            "battery": "std_msgs/msg/UInt16",
            "imu": "sensor_msgs/msg/Imu",
            "scan": "sensor_msgs/msg/LaserScan",
        },
        "service_types": {
            "run_action": "puppy_control_msgs/srv/SetRunActionName",
            "go_home": "std_srvs/srv/Empty",
            "set_bool": "std_srvs/srv/SetBool",
        },
        "highlights": [
            "Decentralized CycloneDDS transport (no single-point-of-failure rosmaster)",
            "Modern slam_toolbox 2.6.8, Nav2 1.1.16, and MoveIt 2.5.5 pre-installed",
            "Supported LTS through May 2027 with native ROSBridge (:9090) & web_video_server (:8080)",
        ],
    },
}


def normalize_ros_mode(distro: Optional[str]) -> str:
    """Normalize any ROS distro label or container name into ``"ros1"`` or ``"ros2"``.

    Args:
        distro: Free-form distro string (e.g. ``"ROS2 Humble"``, ``"humble"``, ``"noetic"``, ``None``).

    Returns:
        ``"ros2"`` when ``distro`` mentions Humble or ROS 2, otherwise ``"ros1"``.
    """
    text = str(distro or "").strip().lower()
    if any(tok in text for tok in ("humble", "ros2", "ros 2", "puppypi_ros2", "jazzy", "kilted")):
        return "ros2"
    return "ros1"


def get_ros_profile(mode_or_distro: Optional[str]) -> Dict[str, Any]:
    """Return the authoritative ROS profile dictionary for a distro or mode string.

    Args:
        mode_or_distro: ``"ros1"``, ``"ros2"``, ``"noetic"``, ``"humble"``, or distro label.

    Returns:
        Copy of the matching profile dictionary from ``ROS_PROFILES``.
    """
    mode = normalize_ros_mode(mode_or_distro)
    return dict(ROS_PROFILES[mode])


def get_ros_comparison_payload() -> Dict[str, Any]:
    """Build the structured ROS 1 Noetic vs. ROS 2 Humble comparison payload for the UI.

    Returns:
        Dictionary containing ``profiles``, ``comparison_rows``, and ``recommendation``.
    """
    r1 = ROS_PROFILES["ros1"]
    r2 = ROS_PROFILES["ros2"]
    comparison_rows: List[Dict[str, str]] = [
        {
            "dimension": "Container & OS Base",
            "ros1": f"{r1['container_name']} — {r1['ubuntu_version']}",
            "ros2": f"{r2['container_name']} — {r2['ubuntu_version']}",
        },
        {
            "dimension": "Middleware & Transport",
            "ros1": r1["middleware"],
            "ros2": r2["middleware"],
        },
        {
            "dimension": "Support Lifecycle",
            "ros1": r1["support_status"],
            "ros2": r2["support_status"],
        },
        {
            "dimension": "SLAM & Mapping",
            "ros1": r1["slam_stack"],
            "ros2": r2["slam_stack"],
        },
        {
            "dimension": "Navigation & Manipulation",
            "ros1": f"{r1['nav_stack']} / {r1['manipulation_stack']}",
            "ros2": f"{r2['nav_stack']} / {r2['manipulation_stack']}",
        },
        {
            "dimension": "ROSBridge Message Types",
            "ros1": "puppy_control/{Velocity,Pose,Gait,SetServo}",
            "ros2": "puppy_control_msgs/msg/{Velocity,Pose,Gait,SetServo}",
        },
        {
            "dimension": "Expansion Board & Services",
            "ros1": "ros_robot_controller/* & puppy_control/SetRunActionName",
            "ros2": "ros_robot_controller_msgs/msg/* & puppy_control_msgs/srv/SetRunActionName",
        },
        {
            "dimension": "FPV Camera Topic",
            "ros1": "/usb_cam/image_raw",
            "ros2": "/image_raw (fallback /usb_cam/image_raw)",
        },
        {
            "dimension": "Config & Mechanics Paths",
            "ros1": f"{r1['env_file_path']} & puppy.py (with_arm=0)",
            "ros2": f"{r2['env_file_path']} & puppy.py (with_arm=1)",
        },
    ]
    return {
        "profiles": {"ros1": dict(r1), "ros2": dict(r2)},
        "comparison_rows": comparison_rows,
        "recommendation": (
            "ROS 2 Humble (CycloneDDS) is recommended for active development, Nav2/slam_toolbox "
            "autonomy, and security patches through May 2027. Keep ROS 1 Noetic when running legacy "
            "Hiwonder OpenCV demo apps."
        ),
    }
