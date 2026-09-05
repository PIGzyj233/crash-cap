import type { ThemeConfig } from 'antd'
import { elevation,fontStack,monoStack,palette,radius,semantic,space } from './tokens'

/**
 * The Ant Design theme, derived from `tokens.ts`.
 *
 * Component tokens are preferred over CSS overrides: four of the rules that
 * used to reach into antd internals from `styles.css` (two of them with
 * `!important`) are expressed here instead, which removes the specificity
 * fight entirely rather than winning it.
 */
export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: semantic.accent,
    colorInfo: semantic.accent,
    colorSuccess: semantic.positive,
    colorWarning: semantic.caution,
    colorError: semantic.critical,
    colorText: semantic.textPrimary,
    colorTextSecondary: semantic.textSecondary,
    colorTextDescription: semantic.textSecondary,
    colorTextHeading: semantic.textHeading,
    colorBorder: semantic.border,
    colorBorderSecondary: semantic.border,
    colorBgLayout: semantic.bgApp,
    colorBgContainer: semantic.bgSurface,
    borderRadius: radius.md,
    borderRadiusLG: radius.lg,
    borderRadiusSM: radius.sm,
    fontFamily: fontStack,
    // Previously unset, so every <Text code> fell back to antd's default stack.
    fontFamilyCode: monoStack,
    boxShadowTertiary: elevation.e1,
    wireframe: false,
  },
  components: {
    Layout: {
      headerBg: semantic.bgSurface,
      siderBg: semantic.navBg,
      bodyBg: semantic.bgApp,
    },
    // These only apply because the Menu is now explicitly theme="dark":
    // antd's Menu defaults to light and SiderContext does not propagate theme,
    // so before that prop these six tokens were inert.
    Menu: {
      darkItemBg: semantic.navBg,
      darkSubMenuItemBg: semantic.navBg,
      darkItemSelectedBg: semantic.navItemSelectedBg,
      darkItemHoverBg: semantic.navItemHoverBg,
      darkItemColor: semantic.navText,
      darkItemSelectedColor: semantic.navTextActive,
      itemBorderRadius: radius.md,
      itemMarginInline: space.x3,
    },
    Card: {
      headerFontSize: 15,
      bodyPadding: space.x5,
      headerPadding: space.x5,
      boxShadowTertiary: elevation.e1,
    },
    Table: {
      headerBg: semantic.bgSubtle,
      headerColor: semantic.textSecondary,
      headerSplitColor: 'transparent',
      rowHoverBg: semantic.accentSubtle,
      borderColor: semantic.border,
      cellPaddingBlockSM: 10,
      cellPaddingInlineSM: space.x3,
    },
    // Replaces the padding / title-margin overrides that styles.css applied to
    // .build-list-item with !important.
    List: {
      itemPadding: `${space.x4}px ${space.x5}px`,
      titleMarginBottom: 2,
    },
    // Replaces the .separate-metrics .ant-statistic-* font-size overrides.
    Statistic: {
      titleFontSize: 11,
      contentFontSize: 21,
    },
    Descriptions: {
      itemPaddingBottom: space.x3,
    },
    Progress: {
      remainingColor: palette.n100,
    },
  },
}
