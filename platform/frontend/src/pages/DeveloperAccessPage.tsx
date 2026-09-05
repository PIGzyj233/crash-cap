import { Button,Card,Space,Typography } from 'antd'
import { PageTitle } from '../components/ui'
import type { Workspace } from '../types'
export function DeveloperAccessPage({ workspace }: { workspace: Workspace }) {
  const command = `crashcap upload .\\Release --workspace ${workspace.name} --build-version 11.0.1.27 --api-url ${window.location.origin}`
  return <div><PageTitle kicker="CLI" title="CLI 上传" description="文件、目标空间和可选版本即可，无需 Git 或配置文件。" /><Space direction="vertical" size="large" style={{ width: '100%' }}><Card title="下载 crashcap"><Space><Button href="/downloads/crashcap/windows-x86_64/crashcap.exe">Windows x64</Button><Button href="/downloads/crashcap/linux-x86_64/crashcap">Linux x64</Button><Button href="/downloads/crashcap/SHA256SUMS">SHA256SUMS</Button></Space></Card><Card title="上传文件或目录"><Typography.Paragraph code copyable>{command}</Typography.Paragraph><Typography.Paragraph>目录会递归发现 EXE、DLL、PDB、DMP。多个路径可一次填写，PE 和 PDB 可以跨批补传。</Typography.Paragraph><Typography.Paragraph code>crashcap upload sdk.dll sdk.pdb --public --build-version 3.2</Typography.Paragraph><Typography.Paragraph>--build-version 可省略。--receipt 指定上传结果文件，--json 输出结构化结果。公共空间不接收 DMP。</Typography.Paragraph></Card></Space></div>
}
