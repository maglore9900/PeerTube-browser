"""Harvest 26 mutations: id -> (production file, subject test file, test name, [(old, new), ...]); each old must occur exactly once."""

W = "engine/server/db/jobs/updater-worker.py"
TW = "tests/active/test_updater_worker.py"
D = "scripts/deploy-bluegreen.sh"
TD = "tests/active/test_deploy_bluegreen.py"
IE = "engine/install-engine-service.sh"
TIE = "tests/active/test_install_engine_service.py"
IU = "engine/install-updater-service.sh"
TIU = "tests/active/test_install_updater_service.py"

ACQUIRE = "                        deploy_lock_fd = acquire_deploy_lock(Path(args.deploy_lock_file), wait_seconds=DEPLOY_LOCK_WAIT_SECONDS)\n"
RESOLVE = "                        engine_unit = engine_instance_unit(parse_upstream_snippet(Path(args.engine_upstream_snippet)))\n"

MUTATIONS = {
    "m01": (W, TW, "test_parse_upstream_snippet_cases", [('lines = path.read_bytes().decode("utf-8").split("\\n")', 'lines = path.read_bytes().decode("utf-8").splitlines()')]),
    "m02": (W, TW, "test_missing_snippet_raises_value_error", [("    except (OSError, UnicodeDecodeError) as exc:\n        raise ValueError(f\"cannot read upstream snippet", "    except UnicodeDecodeError as exc:\n        raise ValueError(f\"cannot read upstream snippet")]),
    "m03": (W, TW, "test_engine_instance_unit_is_the_sudoers_spelling", [('return f"{ENGINE_INSTANCE_BASE}@{port}"', 'return f"{ENGINE_INSTANCE_BASE}@{port}.service"')]),
    "m04": (W, TW, "test_parse_args_takes_snippet_and_deploy_lock", [('default=str((repo_root / "engine/server/db/engine-deploy.lock").resolve()),', 'default=str((repo_root / "engine/server/db/updater-deploy.lock").resolve()),')]),
    "m05": (W, TW, "test_held_lock_raises_and_free_lock_is_taken", [('raise RuntimeError(f"deploy lock {lock_path} still held', 'raise TimeoutError(f"deploy lock {lock_path} still held')]),
    "m06": (W, TW, "test_bounded_wait_runs_out_then_raises", [("    deadline = time.monotonic() + wait_seconds\n    waiting_logged = False", "    deadline = time.monotonic()\n    waiting_logged = False")]),
    "m07": (W, TW, "test_lock_released_during_wait_is_taken", [("                waiting_logged = True\n            time.sleep(poll_seconds)", "                waiting_logged = True\n            time.sleep(max(0.0, deadline - time.monotonic()))")]),
    "m08": (W, TW, "test_read_only_lock_file_is_locked_and_released", [("fd = os.open(lock_path.as_posix(), os.O_RDONLY | os.O_CREAT, 0o644)\n    deadline", "fd = os.open(lock_path.as_posix(), os.O_RDWR | os.O_CREAT, 0o644)\n    deadline")]),
    "m09": (W, TW, "test_main_stops_and_starts_the_snippet_unit_under_the_lock", [(ACQUIRE + RESOLVE, RESOLVE + ACQUIRE)]),
    "m10": (W, TW, "test_main_run_stops_and_starts_the_snippet_unit_holding_the_lock", [('                                service_name=engine_unit,\n                                action="start",', '                                service_name=engine_instance_unit(parse_upstream_snippet(Path(args.engine_upstream_snippet))) if args.engine_upstream_snippet else engine_unit,\n                                action="start",')]),
    "m11": (W, TW, "test_main_run_with_lock_held_through_the_wait_raises_and_stops_nothing", [(ACQUIRE, ""), ("                    service_stopped = True\n", "                    service_stopped = True\n                    if args.engine_upstream_snippet:\n" + ACQUIRE)]),
    "m12": (D, TD, "test_clean_run_switches_then_stops_old_after_7079_names_target", [('systemctl reload nginx || rollback "nginx_reload" "nginx_reload_failed"\n', 'systemctl reload nginx || rollback "nginx_reload" "nginx_reload_failed"\nsystemctl stop "${OLD_UNIT}"\n')]),
    "m13": (D, TD, "test_failure_before_7079_confirms_keeps_old_serving", [('if [[ "${status}" == "200" && "${upstream}" == "${want}" ]]; then', 'if [[ "${status}" == "200" ]]; then')]),
    "m14": (D, TD, "test_refuses_while_updater_runs", [("  active|activating|deactivating|reloading) refuse", "  active|deactivating|reloading) refuse")]),
    "m15": (D, TD, "test_refuses_while_deploy_lock_held", [('flock -n 9 || refuse "lock_held lock=${LOCK_FILE}"', 'flock -n 9 || log_event "lock_held_ignored lock=${LOCK_FILE}"')]),
    "m16": (D, TD, "test_refuses_invalid_snippet", [('ACTIVE_PORT="$(read_active_port "${UPSTREAM_SNIPPET}")" || refuse "snippet_invalid path=${UPSTREAM_SNIPPET}"', 'ACTIVE_PORT="$(read_active_port "${UPSTREAM_SNIPPET}")" || ACTIVE_PORT=7070')]),
    "m17": (D, TD, "test_refuses_client_not_on_7079", [('[[ "$(client_preflight)" != "wrong" ]] || refuse "client_not_on_listener', '[[ "$(client_preflight)" != "wrong" ]] || log_event "client_not_on_listener')]),
    "m18": (D, TD, "test_refuses_non_root", [('[[ "$(id -u)" == "0" ]] || { echo "ERROR: run as root', '[[ "$(id -u)" == "0" || -n "${HOME}" ]] || { echo "ERROR: run as root')]),
    "m19": (D, TD, "test_refuses_foreign_listener_on_target_port", [('[[ "${leftover_status}" == "000" ]] || refuse "port_in_use_by_foreign_process', '[[ "${leftover_status}" == "000" ]] || log_event "port_in_use_by_foreign_process')]),
    "m20": (D, TD, "test_without_blue_green_exits_2_and_creates_no_lock", [("\nBLUE_GREEN=0\n", "\nBLUE_GREEN=1\n")]),
    "m21": ("engine/engine-upstream.sh", "tests/active/test_engine_upstream.py", "test_bash_read_active_port_matches_shared_cases", [('[[ "${count}" == "1" ]] || return 1', '[[ "${count}" -ge 1 ]] || return 1')]),
    "m22": (IE, TIE, "test_prod_install_dry_run_previews_template_listener_and_keeps_snippet_port", [("    listen 127.0.0.1:${ENGINE_LISTENER_PORT};\n", "    listen 127.0.0.1:${ENGINE_LISTENER_PORT};\n    listen [::1]:${ENGINE_LISTENER_PORT};\n")]),
    "m23": (IE, TIE, "test_prod_install_dry_run_refuses_invalid_snippet", [('active_port="$(read_active_port "${UPSTREAM_SNIPPET}")" || fail "Invalid upstream snippet', 'active_port="$(read_active_port "${UPSTREAM_SNIPPET}")" || active_port="${ENGINE_INSTANCE_PORTS[0]}" || fail "Invalid upstream snippet')]),
    "m24": (IE, TIE, "test_prod_install_dry_run_refuses_port_option", [("  (( HOST_SET == 0 && PORT_SET == 0 )) || fail", "  (( HOST_SET == 0 )) || fail")]),
    "m25": (IE, TIE, "test_dev_install_dry_run_preview_unchanged", [('    ENGINE_PORT="${DEFAULT_DEV_ENGINE_PORT}"\n', '    ENGINE_PORT="7070"\n')]),
    "m26": ("engine/uninstall-engine-service.sh", "tests/active/test_uninstall_engine_service.py", "test_prod_uninstall_dry_run_removes_instances_template_listener_then_snippet", [('  run_cmd rm -f "${ENGINE_LISTENER_CONF}"\n  run_cmd rm -f "${UPSTREAM_SNIPPET}" "${UPSTREAM_SNIPPET}.bak"\n', '  run_cmd rm -f "${UPSTREAM_SNIPPET}" "${UPSTREAM_SNIPPET}.bak"\n  run_cmd rm -f "${ENGINE_LISTENER_CONF}"\n')]),
    "m27": ("client/install-client-service.sh", "tests/active/test_install_client_service.py", "test_client_installer_dry_run_defaults_engine_url_per_contour", [("\nDEFAULT_PROD_ENGINE_PORT=7079\n", "\nDEFAULT_PROD_ENGINE_PORT=7070\n")]),
    "m28": ("client/install-client-service.sh", "tests/active/test_install_client_service.py", "test_client_installer_prod_dry_run_keeps_explicit_engine_url", [('if [[ -z "${ENGINE_URL}" ]]; then\n  if [[ "${MODE}" == "prod" ]]; then', 'if [[ -z "${ENGINE_URL}" || "${MODE}" == "prod" ]]; then\n  if [[ "${MODE}" == "prod" ]]; then')]),
    "m29": ("scripts/install-service.sh", "tests/active/test_install_service.py", "test_central_installer_dry_run_points_client_at_contour_engine", [('  if [[ "${contour}" == "dev" ]]; then\n    engine_cmd+=(--host', '  if [[ "${contour}" == "dev" || "${contour}" == "prod" ]]; then\n    engine_cmd+=(--host')]),
    "m30": (IU, TIU, "test_updater_installer_prod_dry_run_passes_snippet_and_allows_only_instance_stop_start", [('engine_units+=("${ENGINE_INSTANCE_BASE}@${port}")', 'engine_units+=("${ENGINE_INSTANCE_BASE}@${port}.service")')]),
    "m31": (IU, TIU, "test_updater_installer_dev_dry_run_keeps_single_name_rule", [('snippet_flag=""\nengine_units=', 'snippet_flag=" --engine-upstream-snippet ${UPSTREAM_SNIPPET}"\nengine_units=')]),
}
