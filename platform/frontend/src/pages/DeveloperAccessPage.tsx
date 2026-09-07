import { Button,Card,Space,Typography } from 'antd'
import { useApi } from '../api/context'
import { PageTitle } from '../components/ui'
import type { Workspace } from '../types'
export function DeveloperAccessPage({ workspace }: { workspace: Workspace }) {
  const apiUrl = new URL(useApi().baseUrl, window.location.origin).toString().replace(/\/$/, '')
  const command = `crashcap upload .\\Release --workspace ${workspace.name} --build-version 11.0.1.27 --api-url ${apiUrl}`
  return <div><PageTitle kicker="CLI" title="接入指南" description="文件、目标空间和可选版本即可，无需 Git 或配置文件。" /><Space direction="vertical" size="large" style={{ width: '100%' }}><Card title="下载 crashcap"><Space><Button href="/downloads/crashcap/windows-x86_64/crashcap.exe">Windows x64</Button><Button href="/downloads/crashcap/linux-x86_64/crashcap">Linux x64</Button><Button href="/downloads/crashcap/SHA256SUMS">SHA256SUMS</Button></Space></Card><Card title="上传文件或目录"><Typography.Paragraph>请先在个人账号页面创建上传令牌；CI 使用管理员签发的 ci-bot 令牌。将令牌配置到 CRASHCAP_TOKEN，或使用 --token-file 指定令牌文件。令牌不会写入上传回执。</Typography.Paragraph><Typography.Paragraph code copyable>{command}</Typography.Paragraph><Typography.Paragraph>目录会递归发现 EXE、DLL、PDB、DMP。多个路径可一次填写，PE 和 PDB 可以跨批补传。</Typography.Paragraph><Typography.Paragraph code copyable>{`crashcap upload sdk.dll sdk.pdb --public --build-version 3.2 --api-url ${apiUrl}`}</Typography.Paragraph><Typography.Paragraph>--build-version 可省略。--receipt 指定上传结果文件，--json 输出结构化结果。公共空间不接收 DMP。</Typography.Paragraph></Card></Space></div>
}
