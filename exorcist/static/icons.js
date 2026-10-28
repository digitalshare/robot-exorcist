// Small inline SVG icon set (stroke-based, currentColor) so the console reads without external assets.
const ICON = {
  arm: '<svg viewBox="0 0 24 24"><path d="M4 20h8M8 20v-4l5-6 3 2-4 6M13 10l4-5 2 1-3 5M17 5l1-2"/><circle cx="8" cy="16" r="1.4"/><circle cx="13" cy="10" r="1.4"/></svg>',
  gripper: '<svg viewBox="0 0 24 24"><path d="M12 3v6M7 9h10v3H7zM8 12l-2 7M16 12l2 7M6 19h3M15 19h3"/></svg>',
  rover: '<svg viewBox="0 0 24 24"><path d="M4 14h16v4H4zM7 14v-4h10v4M12 10V7M10 7h4"/><circle cx="7" cy="19" r="1.6"/><circle cx="17" cy="19" r="1.6"/><path d="M12 4l1.5 1.5M12 4l-1.5 1.5"/></svg>',
  robot: '<svg viewBox="0 0 24 24"><rect x="5" y="8" width="14" height="11" rx="2"/><circle cx="9.5" cy="13" r="1.3"/><circle cx="14.5" cy="13" r="1.3"/><path d="M12 8V4M9 17h6"/></svg>',
  psu: '<svg viewBox="0 0 24 24"><rect x="3" y="7" width="18" height="11" rx="2"/><path d="M13 9l-3 4h4l-3 4"/></svg>',
  bolt: '<svg viewBox="0 0 24 24"><path d="M13 2L5 13h6l-1 9 8-12h-6z"/></svg>',
  logs: '<svg viewBox="0 0 24 24"><path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"/></svg>',
  cluster: '<svg viewBox="0 0 24 24"><circle cx="7" cy="8" r="2.5"/><circle cx="17" cy="7" r="2.5"/><circle cx="12" cy="17" r="2.5"/><path d="M9 9.5l1.5 5M15 9l-1.5 5.5M9.5 8h5"/></svg>',
  triage: '<svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h10M4 18h6M17 15l2 2 3-4"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/></svg>',
  book: '<svg viewBox="0 0 24 24"><path d="M4 5h7a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H4zM20 5h-7a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h8z"/></svg>',
  brain: '<svg viewBox="0 0 24 24"><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3h1V4zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3h-1V4z"/></svg>',
  link: '<svg viewBox="0 0 24 24"><path d="M10 14a4 4 0 0 0 5.6 0l3-3a4 4 0 0 0-5.6-5.6L11.5 7"/><path d="M14 10a4 4 0 0 0-5.6 0l-3 3a4 4 0 0 0 5.6 5.6l1.5-1.5"/></svg>',
  megaphone: '<svg viewBox="0 0 24 24"><path d="M4 10v4h3l7 4V6l-7 4zM17 9a4 4 0 0 1 0 6M7 14l1 5h2"/></svg>',
  ghost: '<svg viewBox="0 0 24 24"><path d="M6 20V10a6 6 0 0 1 12 0v10l-2-2-2 2-2-2-2 2-2-2z"/><circle cx="10" cy="11" r="1"/><circle cx="14" cy="11" r="1"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><path d="M12 3l10 18H2zM12 10v5M12 18v.5"/></svg>',
  slack: '<svg viewBox="0 0 24 24"><path d="M9 4v6M15 14v6M4 15h6M14 9h6"/><rect x="9" y="9" width="6" height="6" rx="1.5"/></svg>',
  github: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M9 20v-3a2 2 0 0 1 1-2 4 4 0 0 1-3-4 4 4 0 0 1 1-3 3 3 0 0 1 0-2 4 4 0 0 1 2 1h4a4 4 0 0 1 2-1 3 3 0 0 1 0 2 4 4 0 0 1 1 3 4 4 0 0 1-3 4 2 2 0 0 1 1 2v3"/></svg>',
};
function icon(name, cls = "") { return `<span class="ico ${cls}">${ICON[name] || ICON.robot}</span>`; }
function systemIcon(kind = "", id = "") {
  const k = (kind + " " + id).toLowerCase();
  if (/arm|ur5|ur3|ur10|manipulator|cobot|franka|kuka/.test(k)) return "arm";
  if (/grip|hand|dynamixel|servo/.test(k)) return "gripper";
  if (/amr|rover|turtlebot|nav2|mobile|agv|base/.test(k)) return "rover";
  return "robot";
}
