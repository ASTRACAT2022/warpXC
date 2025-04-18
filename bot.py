def main():
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('new', new_config),
            MessageHandler(filters.Regex('🆕 Создать конфигурацию'), new_config),
            MessageHandler(filters.Regex('📤 Поделиться конфигурацией'), share_config)
        ],
        states={
            CONFIG_TYPE: [CallbackQueryHandler(handle_config_type)],
            DNS_CHOICE: [CallbackQueryHandler(handle_dns_choice)],
            SHARE_CONFIG: [
                CallbackQueryHandler(handle_share_config, pattern='^share_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_share_config)
            ],
            BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast)],
            ADD_CONFIG: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_config)],
            EDIT_CONFIG: [
                CallbackQueryHandler(select_config_to_edit),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_config)
            ],
            SETTINGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_settings)],
            NOTIFY: [MessageHandler(filters.TEXT & ~filters.COMMAND, notify_user)],
            ALL_USERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_search_users)],
            RESTORE_CONFIGS: [MessageHandler(filters.Document.ALL, process_restore_configs)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('configs', show_configs))
    application.add_handler(MessageHandler(filters.Regex('📂 Мои конфигурации'), show_configs))
    application.add_handler(CallbackQueryHandler(config_action, pattern='^(cfg_|req_|down_|del_|delreq_|share_|test_|back_configs)'))
    application.add_handler(CommandHandler('settings', settings))
    application.add_handler(MessageHandler(filters.Regex('⚙️ Настройки'), settings))
    application.add_handler(CallbackQueryHandler(set_theme, pattern='^theme_'))
    application.add_handler(CallbackQueryHandler(set_language, pattern='^lang_'))
    application.add_handler(CommandHandler('referral', referral))
    application.add_handler(MessageHandler(filters.Regex('📊 Рефералы'), referral_stats))
    application.add_handler(CommandHandler('export', export_configs))
    application.add_handler(MessageHandler(filters.Regex('📤 Экспорт конфигураций'), export_configs))
    application.add_handler(CommandHandler('test', test_config))
    application.add_handler(CallbackQueryHandler(handle_test_config, pattern='^test_'))
    application.add_handler(CommandHandler('help', help_cmd))
    application.add_handler(MessageHandler(filters.Regex('ℹ️ Помощь'), help_cmd))
    application.add_handler(CommandHandler('broadcast', broadcast))
    application.add_handler(CommandHandler('stats', stats))
    application.add_handler(CommandHandler('userinfo', user_info))
    application.add_handler(CommandHandler('addconfig', add_config))
    application.add_handler(CommandHandler('editconfig', edit_config))
    application.add_handler(CommandHandler('listusers', list_users))
    application.add_handler(CommandHandler('allusers', all_users))
    application.add_handler(CallbackQueryHandler(handle_users_list, pattern='^(page_|filter_|sort_|search_|export_|ban_|unban_|notify_|user_|back_users)'))
    application.add_handler(CommandHandler('ban', ban_user_cmd))
    application.add_handler(CommandHandler('unban', unban_user_cmd))
    application.add_handler(CommandHandler('notify', notify))
    application.add_handler(CommandHandler('backup', backup_configs))
    application.add_handler(CommandHandler('restore', restore_configs))
    application.add_handler(CallbackQueryHandler(button_callback))

    application.run_polling()
