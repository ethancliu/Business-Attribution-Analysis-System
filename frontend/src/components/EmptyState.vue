<script setup>
/** 统一的空态占位。 */
defineProps({
  icon: { type: String, default: 'Box' },
  title: { type: String, default: '暂无数据' },
  description: { type: String, default: '' },
})
</script>

<template>
  <div class="empty">
    <el-icon class="empty-icon"><component :is="icon" /></el-icon>
    <div class="empty-title">{{ title }}</div>
    <div v-if="description" class="empty-desc">{{ description }}</div>
    <div v-if="$slots.default" class="empty-extra">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 20px;
  text-align: center;
  color: var(--jy-text-secondary);
}

.empty-icon {
  font-size: 42px;
  color: #d7dbe6;
  margin-bottom: 12px;
}

.empty-title {
  font-size: 15px;
  color: var(--jy-text-regular);
  font-weight: 500;
}

.empty-desc {
  margin-top: 6px;
  font-size: 13px;
  max-width: 420px;
  line-height: 1.7;
}

.empty-extra {
  margin-top: 16px;
}
</style>
