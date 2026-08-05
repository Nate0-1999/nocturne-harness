# Law coverage

Generated deterministically by `scripts/check_test_motivations.py`.

- Tests discovered: 348
- Motivated tests: 40
- Grandfathered baseline debt: 308
- Stale baseline entries: 0

## SPEC and ADR defenders

### 0 — ZERO DEFENDERS

- _None._

### 1 — ZERO DEFENDERS

- _None._

### 1.0 — ZERO DEFENDERS

- _None._

### 1.1 — ZERO DEFENDERS

- _None._

### 1.2 — ZERO DEFENDERS

- _None._

### 1.3 — ZERO DEFENDERS

- _None._

### 1.4 — ZERO DEFENDERS

- _None._

### 2 — ZERO DEFENDERS

- _None._

### 2.1 — ZERO DEFENDERS

- _None._

### ADR-001 — ZERO DEFENDERS

- _None._

### ADR-010 — ZERO DEFENDERS

- _None._

### ADR-002 — ZERO DEFENDERS

- _None._

### ADR-003 — ZERO DEFENDERS

- _None._

### ADR-004 — ZERO DEFENDERS

- _None._

### ADR-005 — 1 defender(s)

- `tests/test_citation.py::test_citation_uses_deterministic_unicode_alphanumeric_ngrams`

### ADR-011 — ZERO DEFENDERS

- _None._

### ADR-007 — ZERO DEFENDERS

- _None._

### ADR-008 — ZERO DEFENDERS

- _None._

### ADR-012 — ZERO DEFENDERS

- _None._

### ADR-013 — ZERO DEFENDERS

- _None._

### ADR-014 — ZERO DEFENDERS

- _None._

### ADR-015 — ZERO DEFENDERS

- _None._

### ADR-016 — ZERO DEFENDERS

- _None._

### ADR-017 — ZERO DEFENDERS

- _None._

### ADR-018 — ZERO DEFENDERS

- _None._

### ADR-019 — 3 defender(s)

- `tests/test_cli.py::test_local_commands_dispatch`
- `tests/test_cli.py::test_parser_exposes_onboarding_and_lifecycle_commands`
- `tests/test_onboarding.py::test_up_orders_container_migration_services_and_browser`

### ADR-020 — ZERO DEFENDERS

- _None._

### ADR-021 — ZERO DEFENDERS

- _None._

### ADR-022 — ZERO DEFENDERS

- _None._

### ADR-023 — ZERO DEFENDERS

- _None._

### ADR-024 — ZERO DEFENDERS

- _None._

### ADR-006 — ZERO DEFENDERS

- _None._

### ADR-009 — ZERO DEFENDERS

- _None._

### B.1 — ZERO DEFENDERS

- _None._

### B.2 — ZERO DEFENDERS

- _None._

### B.3 — ZERO DEFENDERS

- _None._

### B.4 — ZERO DEFENDERS

- _None._

### B.5 — ZERO DEFENDERS

- _None._

### B.6 — 2 defender(s)

- `tests/test_test_motivations.py::test_report_indexes_citations_and_marks_uncovered_law`
- `web/tests/vitals.test.mjs::line-189`

### C.1 — ZERO DEFENDERS

- _None._

### C.2 — ZERO DEFENDERS

- _None._

### C.3 — ZERO DEFENDERS

- _None._

### C.4 — ZERO DEFENDERS

- _None._

### C.5 — ZERO DEFENDERS

- _None._

### C.6 — ZERO DEFENDERS

- _None._

### C.7 — ZERO DEFENDERS

- _None._

### C.8 — ZERO DEFENDERS

- _None._

### C.9 — ZERO DEFENDERS

- _None._

### C.10 — 4 defender(s)

- `web/tests/vitals.test.mjs::line-113`
- `web/tests/vitals.test.mjs::line-148`
- `web/tests/vitals.test.mjs::line-159`
- `web/tests/vitals.test.mjs::line-171`

### D.1 — ZERO DEFENDERS

- _None._

### D.2 — ZERO DEFENDERS

- _None._

### D.3 — ZERO DEFENDERS

- _None._

### D.4 — ZERO DEFENDERS

- _None._

## Other referenced statutes

### A-027

- `tests/test_agent_runtime.py::test_successful_model_response_is_receipted_before_turn_returns`

### A-034

- `web/tests/vitals.test.mjs::line-140`

### A-036

- `tests/test_agent_runtime.py::test_successful_model_response_is_receipted_before_turn_returns`
- `tests/test_citation.py::test_citation_requires_full_short_body_and_ignores_tiny_memories`
- `tests/test_citation.py::test_citation_uses_deterministic_unicode_alphanumeric_ngrams`
- `tests/test_memory_gate.py::test_citation_failure_is_visible_without_retracting_the_turn`
- `tests/test_memory_gate.py::test_citations_follow_each_model_calls_exact_event_source`

### A-038

- `tests/test_fixture_isolation.py::test_fixture_launcher_rejects_owner_port`
- `tests/test_fixture_isolation.py::test_fixture_redirects_to_server_verified_identity`
- `tests/test_fixture_isolation.py::test_fixture_refusal_uses_socket_port_not_spoofable_host`
- `tests/test_receipt_queue.py::test_failed_batch_is_mode_0600_estimated_and_replays_by_stable_id`

### A-040

- `tests/test_test_motivations.py::test_syntax_digest_turns_a_modified_grandfathered_test_into_a_failure`

### A-041

- `tests/test_m2n_lifecycle.py::test_config_rejects_invalid_backup_retention`
- `tests/test_m2n_lifecycle.py::test_future_config_is_refused_without_mutation`
- `tests/test_m2n_lifecycle.py::test_v1_config_upgrades_atomically_without_replacing_owner_values`

### A-042

- `tests/test_cli.py::test_local_commands_dispatch`
- `tests/test_cli.py::test_parser_exposes_onboarding_and_lifecycle_commands`
- `tests/test_m2n_backup.py::test_backup_publishes_verified_private_receipt_and_prunes_known_generations`
- `tests/test_m2n_backup.py::test_doctor_fails_closed_on_a_corrupt_recognized_backup`
- `tests/test_m2n_backup.py::test_doctor_rechecks_resources_and_backup_authority`
- `tests/test_m2n_backup.py::test_failed_dump_publishes_no_generation`
- `tests/test_onboarding.py::test_up_orders_container_migration_services_and_browser`

### A-043

- `tests/test_m2n_backup.py::test_doctor_fails_closed_on_a_corrupt_recognized_backup`
- `tests/test_m2n_backup.py::test_doctor_rechecks_resources_and_backup_authority`

### A-044

- `tests/test_daemon.py::test_dev_app_wires_the_owned_spine_into_the_public_rack_query`
- `tests/test_m2n_resources.py::test_directory_size_ignores_symlinked_content`
- `tests/test_m2n_resources.py::test_resource_watch_enriches_database_truth_with_owner_local_measurements`
- `tests/test_m2n_resources.py::test_resource_watch_keeps_unavailable_rss_distinct_from_zero`
- `tests/test_m2n_resources.py::test_startup_warns_early_without_prompting_or_stopping`
- `web/tests/vitals.test.mjs::line-127`

### A-045

- `tests/test_cli.py::test_local_commands_dispatch`
- `tests/test_cli.py::test_parser_exposes_onboarding_and_lifecycle_commands`
- `tests/test_m2n_backup.py::test_candidate_credential_file_is_private_and_docker_env_compatible`
- `tests/test_m2n_backup.py::test_exact_restore_confirmation_switches_and_retains_candidate`
- `tests/test_m2n_backup.py::test_failed_candidate_switch_restores_the_former_config_and_volume`
- `tests/test_m2n_backup.py::test_restore_cancellation_prints_manifest_and_discards_only_candidate`
- `tests/test_m2n_backup.py::test_restore_refuses_while_owner_services_can_still_write`
- `tests/test_m2n_backup.py::test_rollback_manifest_names_loss_reversion_pins_and_event_deltas`
- `tests/test_m2n_lifecycle.py::test_v2_config_adds_the_existing_compose_volume_without_changing_owner_values`

## Baseline debt

- `tests/contract/test_spine_contract.py::test_live_create_conflicts_and_dedup_bands`
- `tests/contract/test_spine_contract.py::test_live_patch_cas_tombstone_and_list`
- `tests/contract/test_spine_contract.py::test_live_spend_receipt_is_atomic_and_idempotent`
- `tests/test_agent.py::test_resolve_model_uses_settings_key_not_ambient_environment`
- `tests/test_agent.py::test_resolve_model_rejects_missing_settings_key_even_if_ambient_key_exists`
- `tests/test_agent.py::test_resolve_model_uses_pydantic_provider_registry_for_other_model_strings`
- `tests/test_agent.py::test_resolve_model_rejects_a_string_unknown_to_pydantic_ai`
- `tests/test_agent.py::test_resolve_model_normalizes_a_missing_optional_provider_dependency`
- `tests/test_agent.py::test_agent_lazily_resolves_only_the_selected_model`
- `tests/test_agent.py::test_chat_returns_output_and_reusable_full_history_with_exact_limits`
- `tests/test_agent.py::test_label_agent_is_separate_and_has_no_tools`
- `tests/test_agent.py::test_empty_remember_command_is_visible_and_does_not_call_model_or_spine`
- `tests/test_agent.py::test_remember_uses_selected_model_once_without_tools_and_maps_global_user_fact`
- `tests/test_agent.py::test_invalid_generated_label_is_rejected_without_calling_spine`
- `tests/test_agent.py::test_invalid_generated_keywords_are_rejected_without_calling_spine`
- `tests/test_agent.py::test_remember_failures_are_truthful_visible_non_success`
- `tests/test_agent.py::test_near_miss_remember_commands_are_ordinary_chat`
- `tests/test_agent_runtime.py::test_dead_ledger_queues_estimate_and_never_retracts_answer`
- `tests/test_agent_runtime.py::test_streams_typed_deltas_events_cumulative_usage_and_reusable_history`
- `tests/test_agent_runtime.py::test_openrouter_route_settings_are_fresh_sticky_and_price_sorted`
- `tests/test_agent_runtime.py::test_resolution_epochs_break_and_then_repin_openrouter_session_stickiness`
- `tests/test_agent_runtime.py::test_pinned_routes_only_receive_provider_settings_they_can_use`
- `tests/test_agent_runtime.py::test_provider_cache_usage_is_retained_by_the_existing_usage_adapter`
- `tests/test_agent_runtime.py::test_cacheable_prefix_uses_only_the_terminal_provider_response`
- `tests/test_agent_runtime.py::test_remember_dispatch_receives_the_same_thread_model_and_routing_settings`
- `tests/test_agent_runtime.py::test_final_memory_block_is_system_adjacent_not_user_prompt_text`
- `tests/test_agent_runtime.py::test_updated_memory_block_replaces_stale_provider_history`
- `tests/test_agent_runtime.py::test_history_sanitizing_error_path_does_not_duplicate_or_recount_old_turn`
- `tests/test_agent_runtime.py::test_turn_exclusions_are_applied_to_model_visible_search_results`
- `tests/test_agent_runtime.py::test_remember_uses_dispatch_and_emits_its_visible_result`
- `tests/test_agent_runtime.py::test_remember_label_budget_maps_to_budget_exceeded_with_usage`
- `tests/test_agent_runtime.py::test_remember_label_provider_failure_maps_to_error`
- `tests/test_agent_runtime.py::test_usage_limit_maps_to_budget_exceeded_with_partial_history`
- `tests/test_agent_runtime.py::test_provider_failure_maps_to_error_and_preserves_capture_without_cancel_repair`
- `tests/test_agent_runtime.py::test_cancellation_waits_for_tool_and_repairs_history_for_the_next_turn`
- `tests/test_agent_runtime.py::test_tool_cleanup_exception_cannot_mask_cancelled_history_repair`
- `tests/test_cli.py::test_deploy_loads_initialized_key_and_forwards_dry_run`
- `tests/test_cli.py::test_safe_command_error_has_no_traceback`
- `tests/test_cli.py::test_unknown_command_is_rejected_by_argparse`
- `tests/test_commands.py::test_model_command_parses_only_the_exact_direct_command`
- `tests/test_config.py::test_c5_defaults_are_local_minimax_with_bounded_runs_and_spine`
- `tests/test_config.py::test_settings_accept_environment_model_spine_and_limit_overrides`
- `tests/test_config.py::test_positive_configured_limits_are_enforced`
- `tests/test_config.py::test_model_context_tokens_requires_a_real_integer`
- `tests/test_config.py::test_configured_runtime_identities_cannot_be_empty`
- `tests/test_config.py::test_model_policy_chat_rejects_values_outside_a021`
- `tests/test_config.py::test_superseded_model_policy_fields_do_not_exist`
- `tests/test_context_window.py::test_tracker_keeps_measured_total_and_exact_limit_with_estimated_split`
- `tests/test_context_window.py::test_tracker_global_aggregates_only_observed_threads`
- `tests/test_context_window_api.py::test_public_rack_query_returns_current_context_observation`
- `tests/test_context_window_api.py::test_context_history_is_not_fabricated`
- `tests/test_daemon.py::test_serves_built_web_static`
- `tests/test_daemon.py::test_composed_http_routes_precede_the_static_mount`
- `tests/test_daemon.py::test_static_shell_and_rack_frame_have_distinct_frame_policies`
- `tests/test_daemon.py::test_rack_vitals_query_uses_the_injected_reader_before_static_mount`
- `tests/test_daemon.py::test_rack_vitals_query_truthfully_rejects_historical_as_of_without_reading`
- `tests/test_daemon.py::test_unavailable_rack_vitals_returns_503_without_disturbing_chat`
- `tests/test_daemon.py::test_missing_rack_vitals_reader_is_an_explicit_503`
- `tests/test_daemon.py::test_missing_web_build_is_explicit`
- `tests/test_daemon.py::test_dev_build_uses_locked_install_before_vite_build`
- `tests/test_daemon.py::test_default_prompt_gets_fresh_correlated_error_lifecycle`
- `tests/test_daemon.py::test_dev_app_wires_the_real_streaming_agent_adapter`
- `tests/test_daemon.py::test_explicit_pinned_policy_does_not_resolve_unused_chat_model`
- `tests/test_daemon.py::test_dev_gate_round_trip_blocks_validates_commits_and_injects_system_block`
- `tests/test_daemon.py::test_dev_panel_remove_updates_shared_context_for_the_next_model_call`
- `tests/test_daemon.py::test_unimplemented_known_type_uses_fresh_daemon_error`
- `tests/test_daemon.py::test_ws_custom_route_overrides_known_loop_handler`
- `tests/test_daemon.py::test_ws_handler_may_stream_multiple_valid_envelopes`
- `tests/test_daemon.py::test_ws_live_subscription_overflow_closes_for_snapshot_resync`
- `tests/test_daemon.py::test_ws_outbox_overflow_closes_for_snapshot_resync`
- `tests/test_daemon.py::test_ws_cancel_midstream_confirms_and_preserves_partial_work`
- `tests/test_daemon.py::test_ws_duplicate_cancel_while_cleanup_pending_shares_one_confirmation`
- `tests/test_daemon.py::test_ws_queues_prompt_and_runs_it_once_after_terminal_boundary`
- `tests/test_daemon.py::test_ws_reconnect_hydrates_once_from_snapshot_without_delta_replay`
- `tests/test_daemon.py::test_unknown_and_reserved_types_forward_unchanged_or_ignore`
- `tests/test_daemon.py::test_unknown_type_without_forwarder_is_ignored_without_closing`
- `tests/test_daemon.py::test_snapshot_request_is_enqueued_before_a_later_direct_route_response`
- `tests/test_daemon.py::test_ws_rejects_malformed_text_envelope`
- `tests/test_daemon.py::test_ws_rejects_json_parser_limits`
- `tests/test_daemon.py::test_ws_rejects_binary_frame_without_routing`
- `tests/test_daemon.py::test_ws_stops_routing_after_first_malformed_message`
- `tests/test_daemon.py::test_built_static_mode_rejects_unknown_websocket_path`
- `tests/test_deploy.py::test_exact_armed_plan_is_all_noop`
- `tests/test_deploy.py::test_lawful_absent_managed_states_have_only_create_or_forward_update`
- `tests/test_deploy.py::test_every_managed_drift_blocks`
- `tests/test_deploy.py::test_every_foundation_failure_blocks_all_managed_steps`
- `tests/test_deploy.py::test_non_updatable_resources_block_an_update`
- `tests/test_deploy.py::test_database_user_and_url_secret_partial_topologies_block`
- `tests/test_deploy.py::test_dry_run_only_observes_and_never_materializes_or_mutates`
- `tests/test_deploy.py::test_apply_converges_once_then_second_apply_has_zero_mutations`
- `tests/test_deploy.py::test_absent_breaker_requires_tty_before_any_d1_work`
- `tests/test_deploy.py::test_absent_breaker_is_armed_only_through_packaged_source_and_tty`
- `tests/test_deploy.py::test_partial_breaker_blocks_without_source_or_mutation`
- `tests/test_deploy.py::test_exact_canonical_d2_evidence_is_armed`
- `tests/test_deploy.py::test_every_canonical_d2_deviation_is_partial_or_drifted`
- `tests/test_deploy.py::test_untrusted_billing_account_controller_blocks_armed_state`
- `tests/test_deploy.py::test_cloud_run_is_exact_only_with_sole_unconditional_public_invoker`
- `tests/test_deploy.py::test_cloud_run_extra_or_conditional_public_iam_is_drifted`
- `tests/test_deploy.py::test_artifact_image_listing_uses_supported_fully_qualified_package_argv`
- `tests/test_deploy.py::test_sql_user_identity_requires_one_builtin_user`
- `tests/test_deploy.py::test_database_url_round_trips_only_the_exact_cloud_sql_socket_shape`
- `tests/test_deploy.py::test_database_url_rejects_remote_port_extra_query_and_fragment`
- `tests/test_deploy.py::test_packaged_source_materializes_separate_complete_trees`
- `tests/test_deploy.py::test_packaged_breaker_uses_exact_argv_without_shell_or_confirmation_synthesis`
- `tests/test_deploy.py::test_build_and_execute_commands_stay_inside_the_argv_fence`
- `tests/test_deploy.py::test_local_build_rejects_non_single_argv_image_refs`
- `tests/test_deploy.py::test_execute_refuses_non_mutation_and_unknown_stages`
- `tests/test_deploy.py::test_deploy_target_accepts_only_matching_canonical_identifiers`
- `tests/test_deploy.py::test_deploy_target_rejects_unsafe_or_mismatched_identifiers`
- `tests/test_deploy.py::test_preflight_blocks_every_credential_override_before_subprocesses`
- `tests/test_deploy.py::test_subprocess_failure_redacts_secret_input_and_cloud_output`
- `tests/test_deploy.py::test_missing_command_is_normalized_without_leaking_os_error`
- `tests/test_envelope.py::test_valid_c7_envelope_has_named_type_and_typed_payload`
- `tests/test_envelope.py::test_message_types_cover_m1_and_reserved_names`
- `tests/test_envelope.py::test_rejects_invalid_outer_values`
- `tests/test_envelope.py::test_rejects_extra_outer_fields`
- `tests/test_envelope.py::test_rejects_missing_required_outer_fields`
- `tests/test_envelope.py::test_optional_agent_and_thread_ids_may_be_absent_for_untyped_extension`
- `tests/test_envelope.py::test_known_minimum_payloads_are_typed`
- `tests/test_envelope.py::test_memory_panel_payload_is_a_closed_discriminated_union`
- `tests/test_envelope.py::test_memory_panel_rejects_invalid_or_browser_authority_fields`
- `tests/test_envelope.py::test_memory_panel_requires_outer_thread_in_both_directions`
- `tests/test_envelope.py::test_run_delta_is_discriminated`
- `tests/test_envelope.py::test_run_delta_rejects_wrong_variant_shape`
- `tests/test_envelope.py::test_run_usage_requires_strict_nonnegative_integers`
- `tests/test_envelope.py::test_run_done_enforces_stop_reason_partial_invariant`
- `tests/test_envelope.py::test_prompt_submit_requires_nonblank_prompt_and_outer_thread`
- `tests/test_envelope.py::test_gate_commit_requires_outer_thread`
- `tests/test_envelope.py::test_memory_gate_payloads_enforce_exact_c4_member_types`
- `tests/test_envelope.py::test_gate_open_rejects_cards_the_browser_cannot_render_truthfully`
- `tests/test_envelope.py::test_gate_open_rejects_duplicate_membership_across_card_arrays`
- `tests/test_envelope.py::test_wrong_resolution_gate_and_decision_are_typed`
- `tests/test_envelope.py::test_wrong_resolution_rejects_inconsistent_stage_shapes`
- `tests/test_envelope.py::test_thread_snapshot_request_requires_outer_thread`
- `tests/test_envelope.py::test_thread_snapshot_request_extensions_cannot_reclassify_its_direction`
- `tests/test_envelope.py::test_thread_snapshot_response_types_nested_authoritative_state`
- `tests/test_envelope.py::test_resolved_model_extensions_reject_blank_values`
- `tests/test_envelope.py::test_reserved_and_unknown_types_preserve_arbitrary_json`
- `tests/test_envelope.py::test_unknown_type_rejects_non_json_python_payload`
- `tests/test_envelope.py::test_unknown_and_extensible_known_payloads_reject_nonfinite_numbers`
- `tests/test_envelope.py::test_minimum_payload_extensions_are_json_typed_and_preserved`
- `tests/test_envelope.py::test_factory_injects_fresh_ids_timestamps_and_daemon_metadata`
- `tests/test_envelope.py::test_factory_and_generator_emit_valid_ulids`
- `tests/test_envelope.py::test_factory_rejects_invalid_injected_id`
- `tests/test_extraction.py::test_archive_reads_durable_transcript_and_is_idempotent_per_tail`
- `tests/test_extraction.py::test_idle_scheduler_uses_same_archive_path`
- `tests/test_fixture_isolation.py::test_fixture_refuses_owner_port_before_serving_ui`
- `tests/test_fixture_isolation.py::test_every_scenario_app_installs_the_shared_reachability_wall`
- `tests/test_memory_capability.py::test_capability_contract_is_owned_typed_and_frozen`
- `tests/test_memory_capability.py::test_c6_memory_instruction_is_verbatim`
- `tests/test_memory_capability.py::test_owned_save_handler_keeps_project_scope_required_and_force_optional`
- `tests/test_memory_capability.py::test_vanilla_agent_discovers_three_memory_tools_and_instruction`
- `tests/test_memory_capability.py::test_adapted_tool_schemas_defaults_descriptions_and_capability_id`
- `tests/test_memory_capability.py::test_pydantic_ai_capability_imports_are_fenced_to_adapter`
- `tests/test_memory_capability.py::test_adapter_executes_the_owned_feature_handler`
- `tests/test_memory_gate.py::test_first_chat_blocks_commits_and_keeps_system_instructions_current`
- `tests/test_memory_gate.py::test_post_first_turn_rescores_without_gate_and_publishes_ambient_membership`
- `tests/test_memory_gate.py::test_thread_resolution_controls_prepare_context_and_reaches_both_model_paths`
- `tests/test_memory_gate.py::test_later_turn_uses_rerendered_block_and_persistent_exclusions`
- `tests/test_memory_gate.py::test_near_miss_never_preserves_committed_context_and_exclusion`
- `tests/test_memory_gate.py::test_wrong_removal_stays_paused_until_current_unit_is_edited`
- `tests/test_memory_gate.py::test_wrong_resolution_refreshes_a_cas_conflict_then_expires`
- `tests/test_memory_gate.py::test_spine_failure_is_visible_and_fails_open_without_instructions`
- `tests/test_memory_gate.py::test_cancelled_attempt_is_claimed_and_never_invokes_the_model`
- `tests/test_memory_gate.py::test_gate_config_rejects_non_positive_or_boolean_context_windows`
- `tests/test_memory_panel.py::test_refresh_pages_global_active_list_before_principal_filtering`
- `tests/test_memory_panel.py::test_remove_uses_server_injection_then_rebinds_exact_block_and_exclusions`
- `tests/test_memory_panel.py::test_failed_feedback_returns_safe_error_without_mutating_thread_state`
- `tests/test_memory_panel.py::test_panel_error_never_exposes_problem_response_body`
- `tests/test_memory_panel.py::test_remove_waits_for_an_active_model_run_before_feedback_and_mutation`
- `tests/test_memory_panel.py::test_remove_rejects_nonmember_without_contacting_spine`
- `tests/test_memory_panel.py::test_edit_uses_browser_revision_and_daemon_owned_provenance`
- `tests/test_memory_panel.py::test_pin_uses_browser_revision_and_daemon_owned_provenance`
- `tests/test_memory_panel.py::test_patch_cas_conflict_surfaces_current_unit_without_retry`
- `tests/test_memory_panel.py::test_patch_rejects_conflict_unit_outside_requested_principal_boundary`
- `tests/test_memory_panel.py::test_edit_cannot_target_another_principals_memory`
- `tests/test_memory_panel.py::test_context_install_fails_closed_on_unbindable_final_block`
- `tests/test_memory_panel.py::test_context_install_binds_commit_membership_in_rank_order`
- `tests/test_model_policy.py::test_policy_grammar_accepts_exact_five_forms`
- `tests/test_model_policy.py::test_policy_grammar_rejects_every_other_form`
- `tests/test_model_policy.py::test_all_policy_algorithms_follow_one_golden_table`
- `tests/test_model_policy.py::test_elbow_matches_the_a021_worked_example_and_small_frontier_max_rule`
- `tests/test_model_policy.py::test_elbow_ties_fall_to_lower_prompt_price_and_zero_price_is_degenerate`
- `tests/test_model_policy.py::test_lower_hull_retains_collinear_vertices_and_slope_equality_is_inclusive`
- `tests/test_model_policy.py::test_slope_matches_a021_worked_example_and_one_point_is_degenerate`
- `tests/test_model_policy.py::test_extreme_external_decimal_arithmetic_is_a_fail_open_condition`
- `tests/test_model_policy.py::test_model_routes_prefer_standard_use_sole_variant_and_drop_real_ambiguity`
- `tests/test_model_policy.py::test_catalog_normalizes_per_token_prices_and_caches_for_strictly_under_24h`
- `tests/test_model_policy.py::test_catalog_refresh_is_single_flight_and_expired_failure_never_reuses_stale`
- `tests/test_model_policy.py::test_pinned_resolution_bypasses_catalog_and_is_stable_per_thread`
- `tests/test_model_policy.py::test_nonpinned_resolution_joins_context_and_remains_stable_per_thread`
- `tests/test_model_policy.py::test_named_resolution_validates_exact_openrouter_route_without_mutating_thread`
- `tests/test_model_policy.py::test_named_resolution_rejects_non_openrouter_model_strings`
- `tests/test_model_policy.py::test_named_resolution_rejects_unknown_broker_model`
- `tests/test_model_policy.py::test_named_resolution_refetches_models_without_benchmark_dependency`
- `tests/test_model_policy.py::test_named_resolution_requires_exact_broker_id_not_canonical_alias`
- `tests/test_model_policy.py::test_every_degenerate_nonpinned_resolution_fails_open_to_static_pair`
- `tests/test_onboarding.py::test_init_prompts_once_and_generates_private_config`
- `tests/test_onboarding.py::test_init_uses_environment_secret_and_existing_config_is_inert`
- `tests/test_onboarding.py::test_load_rejects_group_or_world_readable_secret_file`
- `tests/test_onboarding.py::test_process_environment_keeps_services_on_the_initialized_home`
- `tests/test_onboarding.py::test_open_requires_reachability_before_launching_browser`
- `tests/test_packaging.py::test_public_distribution_and_lockstep_dependency_metadata`
- `tests/test_packaging.py::test_committed_web_build_has_every_referenced_asset`
- `tests/test_packaging.py::test_packaged_factory_uses_only_the_private_wheel_asset_path`
- `tests/test_parameter_registry.py::test_registry_rejects_unknown_unbound_and_invalid_values`
- `tests/test_parameter_registry.py::test_run_loop_applies_replays_and_publishes_bound_parameter_changes`
- `tests/test_parameter_registry.py::test_selector_uses_named_seam_preserves_overrides_and_journals_refusals`
- `tests/test_parameter_registry.py::test_model_settings_forward_every_real_request_parameter`
- `tests/test_receipt_queue.py::test_unwritable_spool_retains_degraded_memory_batch`
- `tests/test_run_loop.py::test_run_loop_rejects_invalid_resolved_model`
- `tests/test_run_loop.py::test_static_resolved_model_is_authoritative_on_start_and_snapshot`
- `tests/test_run_loop.py::test_policy_resolution_occurs_once_at_first_run_and_is_thread_authoritative`
- `tests/test_run_loop.py::test_model_command_commits_one_journaled_epoch_without_calling_runner`
- `tests/test_run_loop.py::test_model_command_failures_are_visible_and_preserve_epoch_and_prefix`
- `tests/test_run_loop.py::test_current_model_command_refreshes_context_and_starts_new_epoch`
- `tests/test_run_loop.py::test_queued_model_command_changes_only_the_following_turn`
- `tests/test_run_loop.py::test_model_lookup_starts_at_fifo_boundary_after_immediate_queue_ack`
- `tests/test_run_loop.py::test_cancelling_model_lookup_preserves_current_model_and_epoch`
- `tests/test_run_loop.py::test_cancel_awaits_cleanup_preserves_partial_and_coalesces_duplicates`
- `tests/test_run_loop.py::test_gate_blocks_reconnects_validates_once_and_resumes_only_after_dismiss`
- `tests/test_run_loop.py::test_wrong_resolution_replaces_gate_and_validates_current_revision`
- `tests/test_run_loop.py::test_invalid_gate_payload_ends_the_run_instead_of_stranding_the_ui`
- `tests/test_run_loop.py::test_cancel_before_run_task_first_step_still_confirms_once`
- `tests/test_run_loop.py::test_cancel_racing_completed_model_preserves_outcome_for_queued_turn`
- `tests/test_run_loop.py::test_close_does_not_interrupt_cancellation_cleanup_a_second_time`
- `tests/test_run_loop.py::test_slow_sink_is_bounded_without_one_task_per_delta`
- `tests/test_run_loop.py::test_direct_error_worker_is_owned_until_loop_close`
- `tests/test_run_loop.py::test_fifo_runs_once_and_survives_error_and_budget_terminals`
- `tests/test_run_loop.py::test_attach_snapshot_is_atomic_before_new_live_delta`
- `tests/test_run_loop.py::test_cancel_without_outer_thread_finds_run_after_selection_changes`
- `tests/test_run_loop.py::test_usage_regression_terminalizes_as_error_and_stale_cancel_is_scoped`
- `tests/test_seed.py::test_markdown_seed_is_split_before_one_standard_queue_write`
- `tests/test_seed.py::test_seed_rejects_non_markdown_before_model_work`
- `tests/test_spend.py::test_openrouter_receipts_split_price_classes_and_preserve_exact_native_cost`
- `tests/test_spend.py::test_direct_anthropic_fresh_semantics_missing_cost_and_ref_fallback_stay_honest`
- `tests/test_spine_client.py::test_client_exposes_all_spine_routes`
- `tests/test_spine_client.py::test_prepare_request_mirrors_named_c4_fields`
- `tests/test_spine_client.py::test_memory_unit_is_the_shared_c4_shape`
- `tests/test_spine_client.py::test_dedup_and_search_cards_require_nullable_features_and_rank`
- `tests/test_spine_client.py::test_prepare_cards_require_concrete_features_and_rank`
- `tests/test_spine_client.py::test_commit_response_includes_current_wrong_units`
- `tests/test_spine_client.py::test_create_request_has_machine_id_and_similar_band_force`
- `tests/test_spine_client.py::test_create_success_and_similar_bodies_use_v15_shapes`
- `tests/test_spine_client.py::test_create_conflicts_cover_duplicate_and_active_label`
- `tests/test_spine_client.py::test_patch_request_and_exact_success_conflict_bodies`
- `tests/test_spine_client.py::test_list_params_and_response_mirror_stable_paging_contract`
- `tests/test_spine_client.py::test_contract_models_reject_unspecified_fields`
- `tests/test_spine_client.py::test_search_default_is_literal_c4_value`
- `tests/test_spine_client.py::test_prepare_requires_positive_model_context`
- `tests/test_spine_transport.py::test_all_routes_send_exact_http_contract`
- `tests/test_spine_transport.py::test_vitals_rejects_a_numeric_cost_that_would_lose_decimal_wire_truth`
- `tests/test_spine_transport.py::test_vitals_accepts_the_a029_reserved_model_key_escape`
- `tests/test_spine_transport.py::test_vitals_requires_the_exact_a028_gauge_contract`
- `tests/test_spine_transport.py::test_vitals_rejects_dishonest_spend_points`
- `tests/test_spine_transport.py::test_vitals_rejects_noncanonical_or_unconserved_lanes`
- `tests/test_spine_transport.py::test_create_similar_response_is_distinct_from_created_status`
- `tests/test_spine_transport.py::test_create_409_is_a_typed_domain_conflict`
- `tests/test_spine_transport.py::test_patch_409_is_a_typed_domain_conflict`
- `tests/test_spine_transport.py::test_rfc7807_errors_remain_typed_problems`
- `tests/test_spine_transport.py::test_response_contract_violations_are_not_silently_accepted`
- `tests/test_spine_transport.py::test_rfc7807_standard_members_are_optional_but_not_nullable`
- `tests/test_spine_transport.py::test_create_status_and_body_cannot_be_swapped`
- `tests/test_spine_transport.py::test_transport_failure_is_wrapped_without_request_secrets`
- `tests/test_spine_transport.py::test_response_decoding_failure_is_wrapped_as_transport_failure`
- `tests/test_spine_transport.py::test_redirects_are_not_followed`
- `tests/test_spine_transport.py::test_context_manager_closes_caller_supplied_transport`
- `tests/test_spine_transport.py::test_constructor_rejects_missing_connection_values`
- `tests/test_spine_transport.py::test_constructor_rejects_unsafe_base_urls`
- `tests/test_spine_transport.py::test_base_url_normalization_preserves_encoded_path_segments`
- `tests/test_tools_memory.py::test_save_maps_only_trusted_context_scope_and_force`
- `tests/test_tools_memory.py::test_save_rejects_project_scope_without_current_project_before_spine_call`
- `tests/test_tools_memory.py::test_save_blocks_same_run_global_fallback_after_missing_project_context`
- `tests/test_tools_memory.py::test_save_renders_similar_result_without_automatically_forcing_or_retrying`
- `tests/test_tools_memory.py::test_save_never_renders_an_excluded_similar_memory`
- `tests/test_tools_memory.py::test_save_surfaces_hard_duplicate_and_label_conflicts_without_retry`
- `tests/test_tools_memory.py::test_save_never_renders_an_excluded_create_conflict`
- `tests/test_tools_memory.py::test_search_defaults_to_five_current_project_and_preserves_compact_order`
- `tests/test_tools_memory.py::test_search_overfetches_and_never_renders_excluded_gate_removals`
- `tests/test_tools_memory.py::test_search_renders_empty_results_truthfully`
- `tests/test_tools_memory.py::test_search_rejects_invalid_k_without_spine_call`
- `tests/test_tools_memory.py::test_edit_resolves_uuid_before_an_exact_uuid_shaped_label`
- `tests/test_tools_memory.py::test_edit_falls_back_to_exact_label_when_label_is_uuid_shaped`
- `tests/test_tools_memory.py::test_edit_exact_label_is_case_sensitive_and_rejects_substrings`
- `tests/test_tools_memory.py::test_edit_filters_other_principals_and_non_active_rows_locally`
- `tests/test_tools_memory.py::test_edit_cannot_resolve_an_excluded_gate_removal`
- `tests/test_tools_memory.py::test_edit_paginates_principal_wide_without_project_filter`
- `tests/test_tools_memory.py::test_edit_does_not_patch_missing_or_ambiguous_exact_match`
- `tests/test_tools_memory.py::test_edit_patch_is_body_only_with_trusted_metadata_and_expected_revision`
- `tests/test_tools_memory.py::test_edit_retries_revision_conflict_once_with_returned_current_revision`
- `tests/test_tools_memory.py::test_edit_does_not_retry_label_conflict`
- `tests/test_tools_memory.py::test_edit_stops_after_second_revision_conflict_without_third_attempt`
- `tests/test_transcript.py::test_journal_is_private_append_only_and_path_safe`
- `tests/test_transcript.py::test_journal_refuses_a_git_worktree_root`
- `tests/test_transcript.py::test_journal_refuses_a_symlinked_thread_file`
- `tests/test_transcript.py::test_journal_refuses_root_replaced_by_a_directory_symlink`
- `tests/test_transcript.py::test_failed_partial_append_is_rolled_back`
- `tests/test_transcript.py::test_preexisting_incomplete_tail_is_separated_from_new_records`
- `tests/test_transcript.py::test_restart_scans_past_an_incomplete_tail_to_the_last_valid_message`
- `tests/test_transcript.py::test_non_tail_revisions_do_not_move_restart_continuity_backward`
- `tests/test_transcript.py::test_complete_record_is_fsynced_before_append_returns`
- `tests/test_transcript.py::test_prompt_is_captured_before_model_resolution_failure`
- `tests/test_transcript.py::test_capture_failure_poison_stops_unjournaled_work`
- `tests/test_transcript.py::test_in_run_capture_poison_cannot_be_caught_to_start_queued_work`
- `tests/test_transcript.py::test_same_thread_resolution_is_serialized_in_capture_order`
- `tests/test_transcript.py::test_fifo_capture_has_no_dangling_parent_links`
- `tests/test_transcript.py::test_capture_does_not_depend_on_a_live_subscriber`
- `tests/test_transcript.py::test_run_loop_captures_messages_events_model_change_without_serving_on_restart`

## Stale baseline entries

_None._
