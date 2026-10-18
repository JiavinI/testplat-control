import { Empty, Typography } from 'antd'

const purposes: Record<string, string> = {
  unified_login: '登录服务',
  sso: '登录服务',
  portal: '网站服务',
  gsb_web: 'GSB 网站服务',
  gsb: 'API 服务',
  df_admin: 'API 服务',
  df_picker: 'API 服务',
  daifa_admin: 'API 服务',
  daifa_picker: 'API 服务',
  admin_go2: 'API 服务',
  daifa_admin_web: '网站服务',
  daifa_picker_web: '网站服务',
  admin_go2_web: '网站服务',
}

/** 用途只影响展示；逻辑服务名始终与运行时引用一致。 */
export function ServiceHosts({ hosts }: { hosts: Record<string, string> }) {
  const groups = new Map<string, Array<[string, string]>>()
  for (const row of Object.entries(hosts)) {
    const purpose = purposes[row[0]] ?? '其他服务'
    groups.set(purpose, [...(groups.get(purpose) ?? []), row])
  }
  if (groups.size === 0) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="此环境尚未配置服务地址" />
  return (
    <div className="tp-service-hosts" data-testid="environment-hosts">
      {[...groups].map(([purpose, rows]) => (
        <section key={purpose}>
          <Typography.Title level={5}>{purpose}</Typography.Title>
          {rows.map(([name, url]) => (
            <div className="tp-service-host" key={name}>
              <Typography.Text code>{name}</Typography.Text>
              <span className="tp-service-host__url">{url}</span>
            </div>
          ))}
        </section>
      ))}
    </div>
  )
}
