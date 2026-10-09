<script setup>
/** 会话管理模块：新建 / 搜索 / 选择 / 改名 / 删除。 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import EmptyState from '@/components/EmptyState.vue'
import { useConversationStore } from '@/store/conversation'
import { formatRelative, truncate } from '@/utils/format'

const props = defineProps({
  // 选中会话时由父组件决定后续动作（拉历史 + 建长连接）
  compact: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'created'])

const store = useConversationStore()
const renamingId = ref(null)
const renameValue = ref('')
const renameInput = ref(null)

onMounted(() => {
  if (!store.items.length) store.load()
})

async function handleCreate() {
  try {
    const conv = await store.create()
    ElMessage.success(`已创建会话「${conv.title}」`)
    emit('created', conv)
    emit('select', conv.conversation_id)
  } catch (err) {
    ElMessage.error(err?.message || '新建会话失败')
  }
}

function handleSelect(id) {
  store.select(id)
  emit('select', id)
}

function startRename(conv) {
  renamingId.value = conv.conversation_id
  renameValue.value = conv.title
  requestAnimationFrame(() => renameInput.value?.focus())
}

async function commitRename(conv) {
  const title = renameValue.value.trim()
  renamingId.value = null
  if (!title || title === conv.title) return
  try {
    await store.rename(conv.conversation_id, title)
    ElMessage.success('已重命名')
  } catch (err) {
    ElMessage.error(err?.message || '重命名失败')
  }
}

async function handleDelete(conv) {
  try {
    await ElMessageBox.confirm(
      `删除会话「${conv.title}」会同时清理其消息、任务、分析结果、附件以及 uploads/exports/workspace 下的物理文件，且不可恢复。确认删除？`,
      '删除会话',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const res = await store.remove(conv.conversation_id)
    ElMessage.success(
      `已删除 ${res.deleted} 个会话，清理文件 ${res.removed_files} 个，释放 ${res.freed_bytes} 字节`,
    )
    emit('select', null)
  } catch (err) {
    ElMessage.error(err?.message || '删除失败')
  }
}

let searchTimer = null
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => store.load(), 300)
}
</script>

<template>
  <aside class="conv" :class="{ 'conv--compact': compact }">
    <div class="conv-head">
      <div class="conv-title">
        <el-icon><ChatLineSquare /></el-icon>
        <span>我的会话</span>
        <el-tag size="small" type="info" effect="plain" round>{{ store.total }}</el-tag>
      </div>
      <el-button type="primary" size="small" :loading="store.creating" @click="handleCreate">
        <el-icon><Plus /></el-icon>
        新建
      </el-button>
    </div>

    <el-input
      v-model="store.keyword"
      class="conv-search"
      placeholder="按标题搜索会话"
      clearable
      size="small"
      @input="onSearchInput"
      @clear="store.load()"
    >
      <template #prefix><el-icon><Search /></el-icon></template>
    </el-input>

    <div v-loading="store.loading" class="conv-body">
      <EmptyState
        v-if="!store.items.length && !store.loading"
        icon="ChatDotRound"
        title="还没有会话"
        description="新建一个会话，然后提出你的第一个经营问题。"
      />

      <div
        v-for="conv in store.items"
        :key="conv.conversation_id"
        class="conv-item"
        :class="{ active: conv.conversation_id === store.currentId }"
        @click="handleSelect(conv.conversation_id)"
        @dblclick="startRename(conv)"
      >
        <div class="conv-item-main">
          <div v-if="renamingId === conv.conversation_id" class="conv-rename" @click.stop>
            <el-input
              ref="renameInput"
              v-model="renameValue"
              size="small"
              maxlength="255"
              @keyup.enter="commitRename(conv)"
              @keyup.esc="renamingId = null"
              @blur="commitRename(conv)"
            />
          </div>
          <template v-else>
            <div class="conv-item-title">{{ conv.title }}</div>
            <div class="conv-item-preview">
              {{ conv.last_message_preview ? truncate(conv.last_message_preview, 40) : '暂无消息' }}
            </div>
            <div class="conv-item-meta">
              <span>{{ conv.message_count }} 条消息</span>
              <span>·</span>
              <span>{{ formatRelative(conv.last_message_at || conv.created_at) }}</span>
            </div>
          </template>
        </div>

        <el-dropdown
          v-if="renamingId !== conv.conversation_id"
          trigger="click"
          @command="(cmd) => (cmd === 'rename' ? startRename(conv) : handleDelete(conv))"
        >
          <el-icon class="conv-more" @click.stop><MoreFilled /></el-icon>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="rename">
                <el-icon><EditPen /></el-icon>重命名
              </el-dropdown-item>
              <el-dropdown-item command="delete" divided>
                <el-icon><Delete /></el-icon>删除会话
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.conv {
  width: var(--jy-sider-width);
  flex: 0 0 var(--jy-sider-width);
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--jy-bg-card);
  border-right: 1px solid var(--jy-border);
}

.conv-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 14px 8px;
}

.conv-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--jy-text);
}

.conv-search {
  padding: 0 14px 10px;
}

.conv-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 8px 12px;
}

.conv-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 10px 10px;
  border-radius: var(--jy-radius-sm);
  cursor: pointer;
  margin-bottom: 2px;
  transition: background 0.15s;
}

.conv-item:hover {
  background: var(--jy-bg-hover);
}

.conv-item.active {
  background: var(--jy-brand-soft);
}

.conv-item-main {
  flex: 1;
  min-width: 0;
}

.conv-item-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--jy-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-item.active .conv-item-title {
  color: var(--jy-brand-dark);
}

.conv-item-preview {
  font-size: 12px;
  color: var(--jy-text-secondary);
  margin-top: 3px;
  line-height: 1.5;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-item-meta {
  display: flex;
  gap: 4px;
  font-size: 11px;
  color: var(--jy-text-placeholder);
  margin-top: 4px;
}

.conv-more {
  color: var(--jy-text-placeholder);
  padding: 2px;
  border-radius: 4px;
}

.conv-more:hover {
  background: rgba(0, 0, 0, 0.06);
  color: var(--jy-text-regular);
}
</style>
