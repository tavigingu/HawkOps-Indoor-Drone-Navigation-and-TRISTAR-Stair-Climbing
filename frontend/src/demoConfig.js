// ============================================================================
// DEMO / PRESENTATION MODE
// ----------------------------------------------------------------------------
// Set DEMO_MODE = false to return to the fully functional version that talks
// to the real backend (http://localhost:8002). Everything below is only used
// while DEMO_MODE is true. No other files need to change to switch back.
// ============================================================================

export const DEMO_MODE = false;

// Artificial delay (ms) on the landing "Connect" button so the 3D connect
// animation is visible during the presentation.
export const DEMO_CONNECT_DELAY_MS = 2000;

// Mock telemetry shown on the mission screen.
export const DEMO_STATS = {
  battery: 87,
  temperature: 42,
  height: 0,
  is_flying: false,
};

// Height (cm) the drone "reaches" after a mock takeoff (unlocks autopilot).
export const DEMO_TAKEOFF_HEIGHT = 80;

// Checkpoint state per room (pending | entered | exited).
export const DEMO_ROOM_TIMELINE = {
  1: 'exited',
  2: 'exited',
  3: 'entered',
};

export const DEMO_CURRENT_ROOM_INDEX = 3;

export const DEMO_WALL_MEASUREMENTS = {
  front: 2.14,
  left: 1.62,
  right: 1.88,
};

// ----------------------------------------------------------------------------
// Mock room reports. Rooms 1 & 2 are fully scanned (clickable, populated),
// room 3 is still in progress. All entries are non-null so opening any card
// renders instantly without hitting the backend.
// ----------------------------------------------------------------------------

const room1PreEntry = {
  status: 'success',
  level: 'High',
  description:
    'Heavy smoke detected near the ceiling and an active fire source by the right wall. A person appears to be lying on the floor by the far wall. Recommend cautious entry with thermal guidance.',
  response_received: true,
  http_status: 200,
  request_id: 'demo-101',
  image_url: null,
};

const room2PreEntry = {
  status: 'success',
  level: 'Medium',
  description:
    'Light smoke accumulation, no active flames detected. One person seated against the left wall, appears responsive. Air quality degraded but passable.',
  response_received: true,
  http_status: 200,
  request_id: 'demo-102',
  image_url: null,
};

export const DEMO_ROOM_REPORTS = [
  {
    room_index: 1,
    room_label: 'Room 101',
    pre_entry_ai_analysis: room1PreEntry,
    ocr_frames: { full_frame_url: null, crop_url: null },
    live: {
      pre_entry_ai_analysis: room1PreEntry,
      hazards_counts: { fire: 4, smoke: 17 },
      persons_detected: 1,
      frames_analyzed: 263,
      persons_details: [
        {
          track_id: 1,
          posture: 'Lying down',
          confidence: 0.93,
          image_url: null,
          position: { region: 'Far wall / floor', center: [318, 402] },
          medical_analysis: {
            medical_state: 'CRITICAL',
            description:
              'Person detected motionless on the floor near a smoke source. Possible smoke inhalation. Immediate extraction recommended.',
            indicators: ['Unresponsive posture', 'Close to fire source', 'No detected movement'],
          },
        },
      ],
    },
    saved_report: {
      hazards_detected: { fire: true, smoke: true },
      persons_detected: 1,
      frames_analyzed: 263,
      pre_entry_ai_analysis: room1PreEntry,
      persons_details: [
        {
          track_id: 1,
          posture: 'Lying down',
          confidence: 0.93,
          image_url: null,
          position: { region: 'Far wall / floor', center: [318, 402] },
          medical_analysis: {
            medical_state: 'CRITICAL',
            description:
              'Person detected motionless on the floor near a smoke source. Possible smoke inhalation. Immediate extraction recommended.',
            indicators: ['Unresponsive posture', 'Close to fire source', 'No detected movement'],
          },
        },
      ],
    },
  },
  {
    room_index: 2,
    room_label: 'Room 102',
    pre_entry_ai_analysis: room2PreEntry,
    ocr_frames: { full_frame_url: null, crop_url: null },
    live: {
      pre_entry_ai_analysis: room2PreEntry,
      hazards_counts: { fire: 0, smoke: 6 },
      persons_detected: 1,
      frames_analyzed: 198,
      persons_details: [
        {
          track_id: 2,
          posture: 'Seated',
          confidence: 0.88,
          image_url: null,
          position: { region: 'Left wall', center: [142, 305] },
          medical_analysis: {
            medical_state: 'STABLE',
            description:
              'Person seated and responsive against the left wall. No visible injuries. Assist with evacuation.',
            indicators: ['Responsive posture', 'Stable position'],
          },
        },
      ],
    },
    saved_report: {
      hazards_detected: { fire: false, smoke: true },
      persons_detected: 1,
      frames_analyzed: 198,
      pre_entry_ai_analysis: room2PreEntry,
      persons_details: [
        {
          track_id: 2,
          posture: 'Seated',
          confidence: 0.88,
          image_url: null,
          position: { region: 'Left wall', center: [142, 305] },
          medical_analysis: {
            medical_state: 'STABLE',
            description:
              'Person seated and responsive against the left wall. No visible injuries. Assist with evacuation.',
            indicators: ['Responsive posture', 'Stable position'],
          },
        },
      ],
    },
  },
  {
    // Room 3 still scanning — non-null so the card opens without a backend call.
    room_index: 3,
    room_label: null,
    pre_entry_ai_analysis: { status: 'pending' },
    live: { hazards_counts: { fire: 0, smoke: 0 }, persons_detected: 0, frames_analyzed: 41 },
  },
];

// ----------------------------------------------------------------------------
// Mock Mission History (list + per-mission detail) so the History panel is
// fully presentable without a backend.
// ----------------------------------------------------------------------------

export const DEMO_MISSIONS = [
  {
    id: 1,
    started_at: '2026-06-03T09:14:00',
    ended_at: '2026-06-03T09:19:42',
    scan_mode: 'complex',
    start_position: 'hallway',
    room_count: 3,
    status: 'completed',
  },
  {
    id: 2,
    started_at: '2026-06-02T16:02:00',
    ended_at: '2026-06-02T16:05:18',
    scan_mode: 'medium',
    start_position: 'stairwell',
    room_count: 2,
    status: 'aborted',
  },
];

export const DEMO_MISSION_DETAILS = {
  1: {
    success: true,
    mission: DEMO_MISSIONS[0],
    videos: [],
    room_scans: [
      {
        id: 11,
        room_index: 1,
        room_label: 'Room 101',
        hazard_fire: true,
        hazard_smoke: true,
        persons_detected: 1,
        frames_analyzed: 263,
        scan_start: '2026-06-03T09:14:30',
        scan_end: '2026-06-03T09:16:10',
        pre_entry_level: 'DANGER',
        pre_entry_description:
          'Heavy smoke near the ceiling and an active fire source by the right wall. One person detected lying on the floor.',
        persons: [
          {
            id: 111,
            track_id: 1,
            posture: 'Lying down',
            confidence: 0.93,
            medical_state: 'CRITICAL',
            medical_description: 'Motionless on the floor near a smoke source. Immediate extraction recommended.',
          },
        ],
      },
      {
        id: 12,
        room_index: 2,
        room_label: 'Room 102',
        hazard_fire: false,
        hazard_smoke: true,
        persons_detected: 1,
        frames_analyzed: 198,
        scan_start: '2026-06-03T09:16:20',
        scan_end: '2026-06-03T09:17:48',
        pre_entry_level: 'WARNING',
        pre_entry_description: 'Light smoke accumulation, no active flames. One responsive person seated against the left wall.',
        persons: [
          {
            id: 121,
            track_id: 2,
            posture: 'Seated',
            confidence: 0.88,
            medical_state: 'STABLE',
            medical_description: 'Responsive and seated. No visible injuries. Assist with evacuation.',
          },
        ],
      },
      {
        id: 13,
        room_index: 3,
        room_label: 'Room 103',
        hazard_fire: false,
        hazard_smoke: false,
        persons_detected: 0,
        frames_analyzed: 175,
        scan_start: '2026-06-03T09:18:00',
        scan_end: '2026-06-03T09:19:30',
        pre_entry_level: 'SAFE',
        pre_entry_description: 'No hazards detected, room clear of persons.',
        persons: [],
      },
    ],
  },
  2: {
    success: true,
    mission: DEMO_MISSIONS[1],
    videos: [],
    room_scans: [
      {
        id: 21,
        room_index: 1,
        room_label: 'Room 201',
        hazard_fire: false,
        hazard_smoke: true,
        persons_detected: 0,
        frames_analyzed: 142,
        scan_start: '2026-06-02T16:02:30',
        scan_end: '2026-06-02T16:03:50',
        pre_entry_level: 'WARNING',
        pre_entry_description: 'Smoke detected, no persons found before mission was aborted.',
        persons: [],
      },
    ],
  },
};
