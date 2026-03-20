interface Window {
  google?: {
    accounts: {
      id: {
        initialize: (config: Record<string, unknown>) => void;
        renderButton: (
          el: HTMLElement,
          config: Record<string, unknown>,
        ) => void;
        prompt: () => void;
        disableAutoSelect: () => void;
      };
    };
  };
}
