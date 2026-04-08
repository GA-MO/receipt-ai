import { createTheme } from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { Calendar } from "lucide-react";
import { createElement } from "react";

export const theme = createTheme({
  primaryColor: "indigo",
  fontFamily: "IBM Plex Sans Thai, system-ui, sans-serif",
  defaultRadius: "md",
  cursorType: "pointer",
  components: {
    Paper: {
      defaultProps: {
        shadow: "sm",
        radius: "md",
      },
    },
    Button: {
      defaultProps: {
        radius: "md",
      },
    },
    ActionIcon: {
      defaultProps: {
        radius: "md",
      },
    },
    TextInput: {
      defaultProps: {
        radius: "md",
      },
    },
    NumberInput: {
      defaultProps: {
        radius: "md",
      },
    },
    Select: {
      defaultProps: {
        radius: "md",
      },
    },
    Badge: {
      defaultProps: {
        radius: "xl",
      },
    },
    Modal: {
      defaultProps: {
        radius: "lg",
      },
    },
    DatePickerInput: {
      defaultProps: {
        radius: "md",
        leftSection: createElement(Calendar, { size: 16 }),
        leftSectionPointerEvents: "none" as const,
      },
    },
  },
});
