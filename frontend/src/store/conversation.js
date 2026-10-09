/** 会话列表与当前会话（会话管理模块）。 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import * as chatApi from '@/api/chat'

export const useConversationStore = defineStore('conversation', () => {
  const items = ref([])
  const loading = ref(false)
  const keyword = ref('')
  const statusFilter = ref(null)
  const currentId = ref(null)
  const creating = ref(false)

  const current = computed(() => items.value.find((c) => c.conversation_id === currentId.value) || null)
  const total = computed(() => items.value.length)

  async function load() {
    loading.value = true
    try {
      const data = await chatApi.listConversations({
        keyword: keyword.value || undefined,
        status: statusFilter.value || undefined,
      })
      items.value = data.items || []
      // 当前会话被删掉后要清空选中，避免右侧继续渲染已删除会话
      if (currentId.value && !items.value.some((c) => c.conversation_id === currentId.value)) {
        currentId.value = null
      }
      return items.value
    } finally {
      loading.value = false
    }
  }

  async function create(title) {
    creating.value = true
    try {
      const conv = await chatApi.createConversation(title)
      await load()
      currentId.value = conv.conversation_id
      return conv
    } finally {
      creating.value = false
    }
  }

  async function rename(conversationId, title) {
    await chatApi.updateConversation(conversationId, title)
    const target = items.value.find((c) => c.conversation_id === conversationId)
    if (target) target.title = title
  }

  async function remove(conversationIds) {
    const ids = Array.isArray(conversationIds) ? conversationIds : [conversationIds]
    const result = await chatApi.deleteConversations(ids)
    if (ids.includes(currentId.value)) currentId.value = null
    await load()
    return result
  }

  function select(conversationId) {
    currentId.value = conversationId
  }

  function patch(conversationId, patchData) {
    const target = items.value.find((c) => c.conversation_id === conversationId)
    if (target) Object.assign(target, patchData)
  }

  return {
    items,
    loading,
    keyword,
    statusFilter,
    currentId,
    creating,
    current,
    total,
    load,
    create,
    rename,
    remove,
    select,
    patch,
  }
})
