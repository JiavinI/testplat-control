import { App, Button, Space, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ProjectListTable } from '@/features/projects/ProjectListTable'
import { useProjectList } from '@/features/projects/hooks'
import { useRepoList, useSyncRepo } from '@/features/repos/hooks'
import type { ProjectResponse, RepoResponse } from '@/shared/types/project'
import { syncResultLabel } from '@/shared/project/display'
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from '@/shared/ui/AsyncState'
import { formatErrorMessage } from '@/shared/ui/errorMessage'

/**
 * Phase 4.0 项目列表：按仓库分组，只读；同步由服务端配置驱动，无新建/编辑/删除。
 */
export function ProjectListPage() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const listQuery = useProjectList()
  const reposQuery = useRepoList()
  const syncMutation = useSyncRepo()

  const groups = useMemo(() => {
    const projects = listQuery.data ?? []
    const repos = reposQuery.data ?? []
    const byRepo = new Map<string, ProjectResponse[]>()
    for (const p of projects) {
      const list = byRepo.get(p.repo) ?? []
      list.push(p)
      byRepo.set(p.repo, list)
    }
    const ordered: { repo: RepoResponse; projects: ProjectResponse[] }[] = []
    const seen = new Set<string>()
    for (const repo of repos) {
      seen.add(repo.key)
      ordered.push({ repo, projects: byRepo.get(repo.key) ?? [] })
    }
    // 库中有项目但 repos 列表暂缺时补占位（防御；正常同步后不应出现）
    for (const [key, plist] of byRepo) {
      if (!seen.has(key)) {
        ordered.push({
          repo: {
            key,
            branch: '—',
            current_sha: plist[0]?.commit_sha ?? null,
            last_sync_at: null,
            last_sync_result: null,
          },
          projects: plist,
        })
      }
    }
    return ordered
  }, [listQuery.data, reposQuery.data])

  const handleSync = async (repoKey: string) => {
    try {
      const result = await syncMutation.mutateAsync(repoKey)
      if (result.ok) {
        message.success(`仓库 ${repoKey} 同步成功`)
      } else {
        message.error(
          `仓库 ${repoKey} 同步失败：${syncResultLabel(result.category)}`,
        )
      }
    } catch (error) {
      message.error(formatErrorMessage(error))
    }
  }

  const refreshing = listQuery.isFetching || reposQuery.isFetching
  const loading = listQuery.isLoading || reposQuery.isLoading
  const error = listQuery.error ?? reposQuery.error

  const renderBody = () => {
    if (loading) {
      return <LoadingState tip="加载项目列表…" />
    }
    if (listQuery.isError || reposQuery.isError) {
      return (
        <ErrorState
          error={error}
          onRetry={() => {
            void listQuery.refetch()
            void reposQuery.refetch()
          }}
        />
      )
    }
    const hasProjects = (listQuery.data ?? []).length > 0
    const hasRepos = (reposQuery.data ?? []).length > 0
    if (!hasProjects && !hasRepos) {
      return (
        <EmptyState description="尚未配置用例仓库。请在服务端设置 TESTPLAT_REPOS_FILE 后重启并同步。" />
      )
    }
    return (
      <ProjectListTable
        groups={groups}
        loading={refreshing && !loading}
        syncingRepo={syncMutation.isPending ? (syncMutation.variables ?? null) : null}
        onOpen={(p) => navigate(`/projects/${p.repo}/${p.project}`)}
        onSync={(key) => {
          void handleSync(key)
        }}
      />
    )
  }

  return (
    <div>
      <Space
        style={{ width: '100%', justifyContent: 'space-between', marginBottom: 20 }}
        align="center"
      >
        <div>
          <span className="tp-page-kicker">Projects</span>
          <Typography.Title level={3} className="tp-page-title" style={{ margin: 0 }}>
            项目列表
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 14 }}>
            从已登记的 Git 用例仓库同步项目；选择环境后在工作台运行 api / case。
          </Typography.Text>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => {
            void listQuery.refetch()
            void reposQuery.refetch()
          }}
          loading={refreshing}
          aria-label="刷新项目列表"
        >
          刷新
        </Button>
      </Space>

      {renderBody()}
    </div>
  )
}
