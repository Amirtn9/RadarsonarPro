# 🔴 لاگینگ: این ماژول دیگر سیستم لاگ را خودش راه‌اندازی نمی‌کند.
# (باگ نسخه ۴.۰: قبلاً اینجا هم setup_advanced_logging صدا زده می‌شد، هم
# در bot.py - چون این فایل import می‌شد قبل از اینکه bot.py خودش را کانفیگ
# کند، این‌جا با یک log_dir هاردکد زودتر اجرا می‌شد. تنها نقطه‌ی راه‌اندازی
# لاگ الان ابتدای bot.py است؛ اینجا فقط از آن استفاده می‌کنیم.)
import logging
logger = logging.getLogger(__name__)
logger.info("dispatcher.py loaded successfully")

# 🔵 چهارم: بقیه import‌ها
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, 
    MessageHandler, ConversationHandler, filters
)

import bot_logic
import admin_panel
import topics
from cronjob_hub import open_cronjob_hub
from states import *

# ─────────────────────────────────────────────────

def register_all_handlers(app:  Application):
    logger.debug("📝 Starting handler registration...")
    text_filter = filters.TEXT & ~filters.COMMAND
    
    # ==========================================================================
    # 1. CONVERSATION HANDLER (اصلی)
    # ==========================================================================
    conv_handler = ConversationHandler(
        allow_reentry=True,
        entry_points=[
            CommandHandler('start', bot_logic.start),
            # --- Admin Panel ---
            CallbackQueryHandler(admin_panel.add_new_user_start, pattern='^add_new_admin$'),
            CallbackQueryHandler(admin_panel.admin_user_actions, pattern='^admin_u_limit_'),
            CallbackQueryHandler(admin_panel.admin_user_actions, pattern='^admin_u_settime_'),
            CallbackQueryHandler(admin_panel.admin_search_start, pattern='^admin_search_start$'),
            CallbackQueryHandler(bot_logic.admin_backup_restore_start, pattern='^admin_backup_restore_start$'),
            CallbackQueryHandler(admin_panel.admin_broadcast_start, pattern='^admin_broadcast_start$'),
            CallbackQueryHandler(admin_panel.admin_user_servers_report, pattern='^admin_u_servers_'),
            CallbackQueryHandler(admin_panel.admin_search_servers_by_uid_start, pattern='^admin_search_servers_by_uid_start$'),
            CallbackQueryHandler(bot_logic.admin_server_detail_action, pattern='^admin_detail_'),
            CallbackQueryHandler(admin_panel.admin_full_report_global_action, pattern='^admin_full_report_global$'),
            
            # --- Payment ---
            CallbackQueryHandler(bot_logic.admin_payment_settings, pattern='^admin_pay_settings$'),
            CallbackQueryHandler(bot_logic.add_pay_method_start, pattern='^add_pay_method_'),
            CallbackQueryHandler(bot_logic.ask_for_receipt, pattern='^confirm_pay_'),

            # --- Group & Server ---
            CallbackQueryHandler(bot_logic.add_group_start, pattern='^add_group$'),
            CallbackQueryHandler(bot_logic.add_server_start_menu, pattern='^add_server$'),

            # --- Tools & Settings ---
            CallbackQueryHandler(bot_logic.manual_ping_start, pattern='^manual_ping_start$'),
            CallbackQueryHandler(bot_logic.add_channel_start, pattern='^add_channel$'),
            CallbackQueryHandler(bot_logic.ask_custom_interval, pattern='^setcron_custom$'),
            CallbackQueryHandler(bot_logic.edit_expiry_start, pattern='^act_editexpiry_'),
            CallbackQueryHandler(bot_logic.ask_terminal_command, pattern='^cmd_terminal_'),

            # --- Resource Limits ---
            CallbackQueryHandler(bot_logic.resource_settings_menu, pattern='^settings_thresholds$'),
            CallbackQueryHandler(bot_logic.ask_cpu_limit, pattern='^set_cpu_limit$'),
            CallbackQueryHandler(bot_logic.ask_ram_limit, pattern='^set_ram_limit$'),
            CallbackQueryHandler(bot_logic.ask_disk_limit, pattern='^set_disk_limit$'),

            # --- User & Reports ---
            CallbackQueryHandler(bot_logic.user_profile_menu, pattern='^user_profile$'),
            CallbackQueryHandler(bot_logic.web_token_action, pattern='^gen_web_token$'),
            CallbackQueryHandler(bot_logic.send_general_report_action, pattern='^act_global_full_report$'),

            # --- Auto Reboot ---
            CallbackQueryHandler(bot_logic.ask_reboot_time, pattern='^start_set_reboot$'),
            CallbackQueryHandler(bot_logic.auto_reboot_menu, pattern='^auto_reboot_menu$'),
            CallbackQueryHandler(bot_logic.save_auto_reboot_final, pattern='^(savereb_|disable_reboot)'),
            CallbackQueryHandler(bot_logic.dashboard_sort_menu, pattern='^dashboard_sort_menu$'),
            CallbackQueryHandler(bot_logic.set_dashboard_sort_action, pattern='^set_dash_sort_'),
            CallbackQueryHandler(admin_panel.admin_all_servers_report, pattern='^admin_all_servers_'),

            # --- Iran Node ---
            CallbackQueryHandler(bot_logic.monitor_settings_panel, pattern='^monitor_settings_panel$'),
            CallbackQueryHandler(bot_logic.set_iran_monitor_start, pattern='^set_iran_monitor_server$'),
            CallbackQueryHandler(bot_logic.delete_monitor_node, pattern='^delete_monitor_node$'),
            CallbackQueryHandler(bot_logic.update_monitor_node, pattern='^update_monitor_node$'),

            # --- Tunnel Configs ---
            CallbackQueryHandler(bot_logic.add_config_start, pattern='^add_tunnel_config$'),
            CallbackQueryHandler(bot_logic.mode_ask_json, pattern='^mode_add_json$'),
            CallbackQueryHandler(bot_logic.mode_ask_sub, pattern='^mode_add_sub$'),
            CallbackQueryHandler(bot_logic.config_stats_dashboard, pattern='^show_config_stats$'),
            
            # --- Tunnel List ---
            CallbackQueryHandler(bot_logic.tunnel_list_menu, pattern='^tunnel_list_menu$'),
            CallbackQueryHandler(bot_logic.test_single_config, pattern='^test_conf_'),
            CallbackQueryHandler(bot_logic.view_config_action, pattern='^view_conf_'),
            CallbackQueryHandler(bot_logic.delete_config_action, pattern='^del_conf_'),
            
            # --- Config Detail ---
            CallbackQueryHandler(bot_logic.show_config_details, pattern='^conf_detail_'),
            CallbackQueryHandler(bot_logic.copy_config_action, pattern='^copy_conf_'),
            CallbackQueryHandler(bot_logic.qr_config_action, pattern='^qr_conf_'),
            CallbackQueryHandler(bot_logic.manage_single_sub_menu, pattern='^manage_sub_'),
            CallbackQueryHandler(bot_logic.get_sub_links_action, pattern='^get_sub_links_'),
            
            # --- Others ---
            CallbackQueryHandler(topics.setup_group_notify_start, pattern='^setup_group_notify$'),
            CallbackQueryHandler(topics.get_group_id_step, pattern='^get_group_id_step$'),
            CallbackQueryHandler(bot_logic.config_cron_menu, pattern='^settings_conf_cron$'),
            CallbackQueryHandler(bot_logic.set_config_cron_action, pattern='^setconfcron_'),
            CallbackQueryHandler(bot_logic.toggle_config_alert, pattern='^toggle_confalert_'),
            CallbackQueryHandler(bot_logic.header_none_action, pattern='^header_none$'),
            CallbackQueryHandler(lambda u, c: u.callback_query.answer("🔜 به‌زودی!", show_alert=True), pattern='^dev_feature$')
        ],
        states={
            SELECT_ADD_METHOD: [
                CallbackQueryHandler(bot_logic.add_server_step_start, pattern='^add_method_step$'),
                CallbackQueryHandler(bot_logic.add_server_linear_start, pattern='^add_method_linear$'),
                CallbackQueryHandler(bot_logic.cancel_handler_func, pattern='^cancel_flow$'),
            ],
            SELECT_CONFIG_TYPE: [
                CallbackQueryHandler(bot_logic.handle_config_type_selection, pattern='^type_'),
                CallbackQueryHandler(bot_logic.cancel_handler_func, pattern='^cancel_flow$'),
            ],
            GET_LINEAR_DATA: [MessageHandler(text_filter, bot_logic.process_linear_data)],
            topics.GET_GROUP_ID_FOR_TOPICS: [MessageHandler(filters.TEXT & ~filters.COMMAND, topics.perform_group_setup)],
            
            GET_CUSTOM_SMALL_SIZE: [MessageHandler(filters.TEXT, bot_logic.custom_small_handler)],
            GET_CUSTOM_BIG_SIZE: [MessageHandler(filters.TEXT, bot_logic.custom_big_handler)],
            GET_CUSTOM_BIG_INTERVAL: [MessageHandler(filters.TEXT, bot_logic.custom_int_handler)],
            
            ADD_ADMIN_ID: [MessageHandler(text_filter, admin_panel.get_new_user_id)],
            ADD_ADMIN_DAYS: [MessageHandler(text_filter, admin_panel.get_new_user_days)],
            ADMIN_SET_LIMIT: [MessageHandler(text_filter, admin_panel.admin_set_limit_handler)],
            ADMIN_SET_TIME_MANUAL: [MessageHandler(text_filter, admin_panel.admin_set_days_handler)],
            ADMIN_SEARCH_USER: [MessageHandler(text_filter, admin_panel.admin_search_handler)],
            ADMIN_RESTORE_DB: [MessageHandler(filters.Document.ALL, bot_logic.admin_backup_restore_handler)],
            GET_BROADCAST_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, admin_panel.admin_broadcast_send)],
            ADMIN_GET_UID_FOR_REPORT: [MessageHandler(filters.TEXT, admin_panel.admin_report_by_uid_handler)],
            ADMIN_AGENT_PORT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel.admin_agent_port_input)],
            
            ADD_PAY_NET: [MessageHandler(text_filter, bot_logic.get_pay_network)],
            ADD_PAY_ADDR: [MessageHandler(text_filter, bot_logic.get_pay_address)],
            ADD_PAY_HOLDER: [MessageHandler(text_filter, bot_logic.get_pay_holder)],

            GET_GROUP_NAME: [MessageHandler(text_filter, bot_logic.get_group_name)],
            GET_NAME: [MessageHandler(text_filter, bot_logic.get_srv_name)],
            GET_IP: [MessageHandler(text_filter, bot_logic.get_srv_ip)],
            GET_PORT: [MessageHandler(text_filter, bot_logic.get_srv_port)],
            GET_USER: [MessageHandler(text_filter, bot_logic.get_srv_user)],
            GET_PASS: [MessageHandler(text_filter, bot_logic.get_srv_pass)],
            CONFIRM_WS_PORT: [CallbackQueryHandler(bot_logic.confirm_ws_port, pattern='^ws_port_(ok|no)$')],
            GET_CUSTOM_WS_PORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, servers.get_custom_ws_port)],
            GET_EXPIRY: [MessageHandler(text_filter, bot_logic.get_srv_expiry)],
            SELECT_GROUP: [CallbackQueryHandler(bot_logic.select_group)],

            GET_MANUAL_HOST: [MessageHandler(text_filter, bot_logic.perform_manual_ping)],
            GET_CHANNEL_FORWARD: [MessageHandler(filters.ALL & ~filters.COMMAND, bot_logic.get_channel_forward)],
            GET_CUSTOM_INTERVAL: [MessageHandler(text_filter, bot_logic.set_custom_interval_action)],
            GET_CHANNEL_TYPE: [CallbackQueryHandler(bot_logic.set_channel_type_action, pattern='^type_')],
            EDIT_SERVER_EXPIRY: [MessageHandler(text_filter, bot_logic.edit_expiry_save)],
            GET_REMOTE_COMMAND: [
                MessageHandler(text_filter, bot_logic.run_terminal_action),
                CallbackQueryHandler(bot_logic.close_terminal_session, pattern='^exit_terminal$')
            ],

            GET_CPU_LIMIT: [MessageHandler(text_filter, bot_logic.save_cpu_limit)],
            GET_RAM_LIMIT: [MessageHandler(text_filter, bot_logic.save_ram_limit)],
            GET_DISK_LIMIT: [MessageHandler(text_filter, bot_logic.save_disk_limit)],

            GET_REBOOT_TIME: [MessageHandler(text_filter, bot_logic.receive_reboot_time_and_show_freq)],
            GET_RECEIPT: [MessageHandler(filters.PHOTO | filters.Document.IMAGE, bot_logic.process_receipt_upload)],
            
            GET_IRAN_NAME: [MessageHandler(text_filter, bot_logic.get_iran_name), CallbackQueryHandler(bot_logic.cancel_handler_func, pattern='^cancel_flow$')],
            GET_IRAN_IP: [MessageHandler(text_filter, bot_logic.get_iran_ip), CallbackQueryHandler(bot_logic.cancel_handler_func, pattern='^cancel_flow$')],
            GET_IRAN_PORT: [MessageHandler(text_filter, bot_logic.get_iran_port), CallbackQueryHandler(bot_logic.cancel_handler_func, pattern='^cancel_flow$')],
            GET_IRAN_USER: [MessageHandler(text_filter, bot_logic.get_iran_user), CallbackQueryHandler(bot_logic.cancel_handler_func, pattern='^cancel_flow$')],
            GET_IRAN_PASS: [MessageHandler(text_filter, bot_logic.get_iran_pass), CallbackQueryHandler(bot_logic.cancel_handler_func, pattern='^cancel_flow$')],
            
            GET_JSON_CONF: [MessageHandler(filters.TEXT | filters.Document.ALL, bot_logic.process_json_config)],
            GET_SUB_LINK: [MessageHandler(filters.TEXT, bot_logic.process_sub_link)],
            GET_CONFIG_LINKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot_logic.process_add_config)],
            GET_SUB_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot_logic.finalize_sub_adding)],
        },
        fallbacks=[
            CommandHandler('cancel', bot_logic.cancel_handler_func),
            CallbackQueryHandler(bot_logic.cancel_handler_func, pattern='^cancel_flow$'),
            CommandHandler('start', bot_logic.start)
        ]
    )
    app.add_handler(conv_handler)

    # ==========================================================================
    # 2. SECRET KEY HANDLER
    # ==========================================================================
    key_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot_logic.admin_key_restore_start, pattern='^admin_key_restore_start$')],
        states={
            ADMIN_RESTORE_KEY: [MessageHandler(filters.Document.ALL, bot_logic.admin_key_restore_handler)]
        },
        fallbacks=[CallbackQueryHandler(bot_logic.cancel_handler_func, pattern='^cancel_flow$')]
    )
    app.add_handler(key_conv_handler)

    # ==========================================================================
    # 3. COMMANDS
    # ==========================================================================
    app.add_handler(CommandHandler('dashboard', bot_logic.dashboard_command))
    app.add_handler(CommandHandler('setting', bot_logic.settings_command))

    # ==========================================================================
    # 4. CALLBACKS (دکمه‌های ساده)
    # ==========================================================================
    # دیکشنری پترن‌ها برای تمیزی کد
    simple_patterns = {
        '^main_menu$': bot_logic.main_menu,
        '^status_dashboard$': bot_logic.status_dashboard,
        '^dashboard_sort_menu$': bot_logic.dashboard_sort_menu,
        '^set_dash_sort_': bot_logic.set_dashboard_sort_action,
        '^del_list_item_': bot_logic.delete_item_from_list_action,

        # Multi-delete servers
        '^srv_multidel_start$': bot_logic.srv_multidel_start,
        '^srv_multidel_toggle_': bot_logic.srv_multidel_toggle,
        '^srv_multidel_confirm$': bot_logic.srv_multidel_confirm,
        '^srv_multidel_cancel$': bot_logic.srv_multidel_cancel,
        
        '^admin_panel_main$': admin_panel.admin_panel_main,
        '^admin_agent_dashboard$': admin_panel.admin_agent_dashboard,
        '^admin_agent_logs$': admin_panel.admin_agent_logs_menu,
        '^admin_agent_install_menu$': admin_panel.admin_agent_install_menu,
        '^admin_agent_install_': admin_panel.admin_agent_install_run,
        '^admin_agent_log_': admin_panel.admin_agent_log_view,
        '^admin_agent_reconnect_all$': admin_panel.admin_agent_reconnect_all,
        '^admin_users_page_': admin_panel.admin_users_list,
        '^admin_u_manage_': admin_panel.admin_user_manage,
        '^admin_u_': admin_panel.admin_user_actions,
        '^admin_users_text$': admin_panel.admin_users_text,
        # 🔧 رفع نسخه ۴.۰: این ۴ خط با ۴ خط بالاتر (admin_agent_*) کاملاً
        # تکراری بودند (کپی-پیست) و حذف شدند.
        '^admin_backup_get$': bot_logic.admin_backup_get,
        '^admin_all_servers_': admin_panel.admin_all_servers_report,
        
        '^groups_menu$': bot_logic.groups_menu,
        '^delgroup_': bot_logic.delete_group_action,
        '^list_groups_for_servers$': bot_logic.list_groups_for_servers,
        '^(listsrv_|list_all)': bot_logic.show_servers,
        '^detail_': bot_logic.server_detail,
        '^act_': bot_logic.server_actions,
        '^manage_servers_list$': bot_logic.manage_servers_list,
        '^toggle_active_': bot_logic.toggle_server_active_action,
        '^show_server_stats$': bot_logic.show_server_stats,
        
        '^tunnel_list_menu$': bot_logic.tunnel_list_menu,
        '^mass_update_test_all$': bot_logic.mass_update_test_start,
        '^list_mode_': bot_logic.show_tunnels_by_mode,
        '^update_all_tunnels$': bot_logic.update_all_configs_status,
        '^test_conf_': bot_logic.test_single_config,
        '^view_conf_': bot_logic.view_config_action,
        '^del_conf_': bot_logic.delete_config_action,
        '^manage_sub_': bot_logic.manage_single_sub_menu,
        '^update_sub_': bot_logic.manual_update_sub_action,
        '^del_sub_full_': bot_logic.delete_full_subscription,
        
        '^conf_detail_': bot_logic.show_config_details,
        '^copy_conf_': bot_logic.copy_config_action,
        '^qr_conf_': bot_logic.qr_config_action,
        '^get_sub_links_': bot_logic.get_sub_links_action,
        
        '^monitor_settings_panel$': bot_logic.monitor_settings_panel,
        '^delete_monitor_node$': bot_logic.delete_monitor_node,
        '^update_monitor_node$': bot_logic.update_monitor_node,
        
        '^wallet_menu$': bot_logic.wallet_menu,
        '^referral_menu$': bot_logic.referral_menu,
        '^buy_plan_': bot_logic.select_payment_method,
        '^pay_method_': bot_logic.show_payment_details,
        '^del_pay_method_': bot_logic.delete_payment_method_action,
        '^admin_approve_pay_': bot_logic.admin_approve_payment_action,
        '^admin_reject_pay_': bot_logic.admin_reject_payment_action,
        
        '^global_ops_menu$': bot_logic.global_ops_menu,
        '^glob_act_': bot_logic.global_action_handler,
        
        '^settings_menu$': bot_logic.settings_menu,
        '^setdns_': bot_logic.set_dns_action,
        '^channels_menu$': bot_logic.channels_menu,
        '^delchan_': bot_logic.delete_channel_action,
        '^menu_schedules$': bot_logic.schedules_settings_menu,
        '^settings_cron$': bot_logic.settings_cron_menu,
        '^setcron_': bot_logic.set_cron_action,
        '^toggle_downalert_': bot_logic.toggle_down_alert,
        '^send_general_report$': bot_logic.send_general_report_action,
        
        '^advanced_monitoring_settings$': bot_logic.advanced_monitoring_settings,
        '^set_small_size_menu$': bot_logic.set_small_size_menu,
        '^set_big_size_menu$': bot_logic.set_big_size_menu,
        '^set_big_interval_menu$': bot_logic.set_big_interval_menu,
        '^save_': bot_logic.save_setting_action,
        
        '^auto_up_menu$': bot_logic.auto_update_menu,
        '^set_autoup_': bot_logic.save_auto_schedule,
        '^(savereb_|disable_reboot)': bot_logic.save_auto_reboot_final,
        
        '^open_add_menu$': bot_logic.show_add_service_menu,
        '^open_lists_menu$': bot_logic.show_lists_menu,
        '^open_account_menu$': bot_logic.show_account_menu,
        '^refresh_conf_dash_ping$': bot_logic.refresh_conf_dash_action,
        '^admin_key_backup_get$': bot_logic.admin_key_backup_get,

        # 🔧 رفع نسخه ۴.۰: این دکمه ساخته شده بود ولی هیچ‌جا رجیستر نشده بود
        '^cronjob_hub_main$': open_cronjob_hub,
    }

    for ptrn, func in simple_patterns.items():
        app.add_handler(CallbackQueryHandler(func, pattern=ptrn))
