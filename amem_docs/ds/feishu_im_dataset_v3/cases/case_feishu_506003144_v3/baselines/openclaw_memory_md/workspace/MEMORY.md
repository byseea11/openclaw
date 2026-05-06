# Durable Memory

- session_handoff_thread: static_memory_stale_state / 【研发/林晨】更新一下，之前那个 owner 口径已经作废，当前接手人和窗口判断都需要按新安排重算。
- session_main_chat: static_memory_stale_state / 【研发/林晨】明确一下 current state：现在只认最新一轮确认过的 owner、blocker 和依赖状态，不再沿用旧说法。
